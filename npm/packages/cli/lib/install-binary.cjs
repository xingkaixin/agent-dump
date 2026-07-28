const fs = require("node:fs");
const crypto = require("node:crypto");
const fsp = require("node:fs/promises");
const http = require("node:http");
const https = require("node:https");
const path = require("node:path");
const zlib = require("node:zlib");

const { getBinarySpec } = require("./targets.cjs");

const DEFAULT_REGISTRY_URL = "https://registry.npmjs.org";
const DEFAULT_RETRY_COUNT = 5;
const DEFAULT_RETRY_DELAY_MS = 3000;

// 上限按当前真实产物定，留足余量但仍能挡住恶意响应：
// registry metadata 现约 45 KB（每个版本约 3 KB），最大的 binary 是 linux-x64 的
// 16.3 MB，压缩后约 6 MB。解压上限同时是 gzip bomb 的防线——64 MB 的压缩流按
// 1000:1 能解出 64 GB。
const MAX_METADATA_BYTES = 16 * 1024 * 1024;
const MAX_COMPRESSED_TARBALL_BYTES = 64 * 1024 * 1024;
const MAX_DECOMPRESSED_TAR_BYTES = 128 * 1024 * 1024;
// 连接建立后 30 秒没有任何字节即判定停滞；整次取用最长 5 分钟，够慢网络下载 16 MB
const DEFAULT_IDLE_TIMEOUT_MS = 30_000;
const DEFAULT_TOTAL_TIMEOUT_MS = 300_000;

function getPackageRoot(rootDir = __dirname) {
  return path.resolve(rootDir, "..");
}

function getRegistryBaseUrl(env = process.env) {
  const rawUrl = env.AGENT_DUMP_NPM_REGISTRY_URL || env.npm_config_registry || DEFAULT_REGISTRY_URL;
  return rawUrl.replace(/\/+$/, "");
}

function sha256(buffer) {
  return crypto.createHash("sha256").update(buffer).digest("hex");
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function fetchBuffer(url, options = {}) {
  if (options.fetchBufferImpl) {
    return options.fetchBufferImpl(url);
  }

  const maxRedirects = options.maxRedirects ?? 5;
  const maxBytes = options.maxBytes ?? MAX_COMPRESSED_TARBALL_BYTES;
  const idleTimeoutMs = options.idleTimeoutMs ?? DEFAULT_IDLE_TIMEOUT_MS;
  // redirect 继承同一个绝对 deadline：否则每一跳都能重置预算，重定向链就成了无限期挂起
  const deadline = options.deadline ?? Date.now() + (options.totalTimeoutMs ?? DEFAULT_TOTAL_TIMEOUT_MS);

  return new Promise((resolve, reject) => {
    let settled = false;
    let request = null;
    let response = null;

    const cleanup = () => {
      clearTimeout(totalTimer);
      // Node 的 setTimeout 只发事件，不 destroy 就不会关掉 socket——挂起的请求
      // 永远不会 reject，外层重试也就永远轮不到
      response?.destroy();
      request?.destroy();
    };

    const fail = (error) => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(error);
    };

    const succeed = (value) => {
      if (settled) return;
      settled = true;
      clearTimeout(totalTimer);
      resolve(value);
    };

    const remaining = deadline - Date.now();
    if (remaining <= 0) {
      settled = true;
      reject(new Error(`Timed out before fetching ${url}`));
      return;
    }

    const totalTimer = setTimeout(() => fail(new Error(`Timed out fetching ${url}`)), remaining);
    totalTimer.unref?.();

    const transport = url.startsWith("https:") ? https : http;
    request = transport.get(
      url,
      {
        headers: options.headers
      },
      (res) => {
        response = res;
        const { statusCode = 0, headers } = res;

        if (statusCode >= 300 && statusCode < 400 && headers.location) {
          if (maxRedirects <= 0) {
            fail(new Error(`Too many redirects while fetching ${url}`));
            return;
          }

          const nextUrl = new URL(headers.location, url).toString();
          settled = true;
          cleanup();
          resolve(fetchBuffer(nextUrl, { ...options, maxRedirects: maxRedirects - 1, deadline, maxBytes }));
          return;
        }

        if (statusCode < 200 || statusCode >= 300) {
          fail(new Error(`Request to ${url} failed with status ${statusCode}`));
          return;
        }

        const declared = Number.parseInt(headers["content-length"] ?? "", 10);
        if (Number.isFinite(declared) && declared > maxBytes) {
          fail(new Error(`Response for ${url} declares ${declared} bytes, over the ${maxBytes} byte limit`));
          return;
        }

        const chunks = [];
        let received = 0;
        res.on("data", (chunk) => {
          received += chunk.length;
          // Content-Length 可以撒谎或缺失，逐 chunk 计数才是真正的上限
          if (received > maxBytes) {
            fail(new Error(`Response for ${url} exceeded the ${maxBytes} byte limit`));
            return;
          }
          chunks.push(chunk);
        });
        res.once("aborted", () => fail(new Error(`Connection aborted while fetching ${url}`)));
        res.once("error", (error) => fail(error));
        res.once("end", () => succeed(Buffer.concat(chunks)));
      }
    );

    request.setTimeout(idleTimeoutMs, () => {
      fail(new Error(`No data for ${idleTimeoutMs}ms while fetching ${url}`));
    });
    request.once("error", (error) => fail(error));
  });
}

async function fetchJson(url, options = {}) {
  const buffer = await fetchBuffer(url, { ...options, maxBytes: options.maxBytes ?? MAX_METADATA_BYTES });
  return JSON.parse(buffer.toString("utf8"));
}

async function withRetries(operation, options = {}) {
  const retries = options.retries ?? DEFAULT_RETRY_COUNT;
  const delayMs = options.delayMs ?? DEFAULT_RETRY_DELAY_MS;

  let lastError = null;
  for (let attempt = 1; attempt <= retries; attempt += 1) {
    try {
      return await operation();
    } catch (error) {
      lastError = error;
      if (attempt === retries) {
        break;
      }

      await delay(delayMs);
    }
  }

  throw lastError;
}

function parseTarEntries(tarBuffer) {
  const entries = new Map();
  let offset = 0;

  while (offset + 512 <= tarBuffer.length) {
    const header = tarBuffer.subarray(offset, offset + 512);
    const empty = header.every((byte) => byte === 0);
    if (empty) {
      break;
    }

    const name = header
      .subarray(0, 100)
      .toString("utf8")
      .replace(/\0.*$/, "");
    const prefix = header
      .subarray(345, 500)
      .toString("utf8")
      .replace(/\0.*$/, "");
    const fullName = prefix ? `${prefix}/${name}` : name;
    const sizeOctal = header
      .subarray(124, 136)
      .toString("utf8")
      .replace(/\0.*$/, "")
      .trim();
    const size = Number.parseInt(sizeOctal || "0", 8);

    const contentStart = offset + 512;
    const contentEnd = contentStart + size;
    entries.set(fullName, tarBuffer.subarray(contentStart, contentEnd));

    offset = contentStart + Math.ceil(size / 512) * 512;
  }

  return entries;
}

function extractBinaryFromTarball(tarballBuffer, spec, options = {}) {
  const maxOutputLength = options.maxDecompressedBytes ?? MAX_DECOMPRESSED_TAR_BYTES;

  let tarBuffer;
  try {
    // 用 zlib 自带的输出上限：先无界解压再检查大小的话，内存早就已经用掉了
    tarBuffer = zlib.gunzipSync(tarballBuffer, { maxOutputLength });
  } catch (error) {
    if (error.code === "ERR_BUFFER_TOO_LARGE") {
      throw new Error(
        `Package tarball for ${spec.packageName} decompresses past the ${maxOutputLength} byte limit`
      );
    }
    throw error;
  }

  const entries = parseTarEntries(tarBuffer);
  const entryName = `package/bin/${spec.executableName}`;
  const binaryBuffer = entries.get(entryName);

  if (!binaryBuffer) {
    throw new Error(`Package tarball for ${spec.packageName} does not contain ${entryName}`);
  }

  return binaryBuffer;
}

async function readChecksums(packageRoot, options = {}) {
  if (options.readChecksumsImpl) {
    return options.readChecksumsImpl(packageRoot);
  }

  const checksumPath = path.join(packageRoot, "lib", "binary-checksums.json");
  const raw = await fsp.readFile(checksumPath, "utf8");
  return JSON.parse(raw);
}

async function readPackageVersion(packageRoot, options = {}) {
  if (options.readPackageVersionImpl) {
    return options.readPackageVersionImpl(packageRoot);
  }

  const packageJsonPath = path.join(packageRoot, "package.json");
  const raw = await fsp.readFile(packageJsonPath, "utf8");
  return JSON.parse(raw).version;
}

function getVendorBinaryPath(packageRoot, spec) {
  return path.join(packageRoot, "vendor", spec.target, spec.executableName);
}

function isBinaryInstalled(options = {}) {
  const platform = options.platform || process.platform;
  const arch = options.arch || process.arch;
  const packageRoot = options.packageRoot || getPackageRoot();
  const existsSync = options.existsSync || fs.existsSync;
  const spec = options.spec || getBinarySpec(platform, arch);
  const vendorPath = getVendorBinaryPath(packageRoot, spec);
  return existsSync(vendorPath);
}

async function installBinary(options = {}) {
  const platform = options.platform || process.platform;
  const arch = options.arch || process.arch;
  const env = options.env || process.env;
  const packageRoot = options.packageRoot || getPackageRoot();
  const spec = getBinarySpec(platform, arch);
  const version = options.version || (await readPackageVersion(packageRoot, options));
  const checksums = options.checksums || (await readChecksums(packageRoot, options));
  const expectedChecksum = checksums?.[version]?.[spec.target];

  if (!expectedChecksum) {
    throw new Error(`Missing checksum for ${spec.target} at version ${version}`);
  }

  const tarballPath = options.tarballPath || env.AGENT_DUMP_CLI_TARBALL_PATH;
  let tarballBuffer;

  if (tarballPath) {
    tarballBuffer = await fsp.readFile(tarballPath);
  } else {
    const registryBaseUrl = options.registryBaseUrl || getRegistryBaseUrl(env);
    const metadataUrl = `${registryBaseUrl}/${encodeURIComponent(spec.packageName)}`;
    const metadata = await withRetries(
      () => fetchJson(metadataUrl, { ...options, maxBytes: options.maxMetadataBytes ?? MAX_METADATA_BYTES }),
      {
        retries: options.retries,
        delayMs: options.retryDelayMs
      }
    );
    const versionMetadata = metadata.versions?.[version];

    if (!versionMetadata?.dist?.tarball) {
      throw new Error(`Registry metadata for ${spec.packageName}@${version} does not include a tarball URL`);
    }

    const tarballUrl = versionMetadata.dist.tarball;
    tarballBuffer = await withRetries(
      () => fetchBuffer(tarballUrl, { ...options, maxBytes: options.maxTarballBytes ?? MAX_COMPRESSED_TARBALL_BYTES }),
      {
        retries: options.retries,
        delayMs: options.retryDelayMs
      }
    );
  }

  const binaryBuffer = extractBinaryFromTarball(tarballBuffer, spec, options);
  const actualChecksum = sha256(binaryBuffer);

  if (actualChecksum !== expectedChecksum) {
    throw new Error(
      `Checksum mismatch for ${spec.packageName}@${version}: expected ${expectedChecksum}, got ${actualChecksum}`
    );
  }

  const vendorPath = getVendorBinaryPath(packageRoot, spec);
  await fsp.mkdir(path.dirname(vendorPath), { recursive: true });
  await fsp.writeFile(vendorPath, binaryBuffer);

  if (!vendorPath.endsWith(".exe")) {
    await fsp.chmod(vendorPath, 0o755);
  }

  return vendorPath;
}

async function ensureBinary(options = {}) {
  const platform = options.platform || process.platform;
  const arch = options.arch || process.arch;
  const packageRoot = options.packageRoot || getPackageRoot();
  const spec = options.spec || getBinarySpec(platform, arch);

  if (isBinaryInstalled({ ...options, platform, arch, packageRoot, spec })) {
    return getVendorBinaryPath(packageRoot, spec);
  }

  return installBinary({ ...options, platform, arch, packageRoot, spec });
}

async function installBinaryFromPackage() {
  if (process.env.AGENT_DUMP_CLI_SKIP_INSTALL === "1") {
    return;
  }

  try {
    await ensureBinary();
  } catch (error) {
    process.stderr.write(`Failed to install agent-dump native binary: ${error.message}\n`);
    process.exitCode = 1;
  }
}

module.exports = {
  DEFAULT_IDLE_TIMEOUT_MS,
  DEFAULT_REGISTRY_URL,
  DEFAULT_RETRY_COUNT,
  DEFAULT_RETRY_DELAY_MS,
  DEFAULT_TOTAL_TIMEOUT_MS,
  MAX_COMPRESSED_TARBALL_BYTES,
  MAX_DECOMPRESSED_TAR_BYTES,
  MAX_METADATA_BYTES,
  ensureBinary,
  extractBinaryFromTarball,
  fetchBuffer,
  fetchJson,
  getPackageRoot,
  getRegistryBaseUrl,
  getVendorBinaryPath,
  installBinary,
  installBinaryFromPackage,
  isBinaryInstalled,
  parseTarEntries,
  readChecksums,
  sha256,
  withRetries
};

if (require.main === module) {
  installBinaryFromPackage();
}
