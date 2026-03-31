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
  return new Promise((resolve, reject) => {
    const transport = url.startsWith("https:") ? https : http;
    const request = transport.get(
      url,
      {
        headers: options.headers
      },
      (response) => {
        const { statusCode = 0, headers } = response;

        if (statusCode >= 300 && statusCode < 400 && headers.location) {
          response.resume();
          if (maxRedirects <= 0) {
            reject(new Error(`Too many redirects while fetching ${url}`));
            return;
          }

          const nextUrl = new URL(headers.location, url).toString();
          resolve(fetchBuffer(nextUrl, { ...options, maxRedirects: maxRedirects - 1 }));
          return;
        }

        if (statusCode < 200 || statusCode >= 300) {
          response.resume();
          reject(new Error(`Request to ${url} failed with status ${statusCode}`));
          return;
        }

        const chunks = [];
        response.on("data", (chunk) => chunks.push(chunk));
        response.on("end", () => resolve(Buffer.concat(chunks)));
      }
    );

    request.once("error", reject);
  });
}

async function fetchJson(url, options = {}) {
  const buffer = await fetchBuffer(url, options);
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

function extractBinaryFromTarball(tarballBuffer, spec) {
  const tarBuffer = zlib.gunzipSync(tarballBuffer);
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
      () => fetchJson(metadataUrl, options),
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
      () => fetchBuffer(tarballUrl, options),
      {
        retries: options.retries,
        delayMs: options.retryDelayMs
      }
    );
  }

  const binaryBuffer = extractBinaryFromTarball(tarballBuffer, spec);
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
  DEFAULT_REGISTRY_URL,
  DEFAULT_RETRY_COUNT,
  DEFAULT_RETRY_DELAY_MS,
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
