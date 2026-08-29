const fs = require("node:fs");
const { spawn } = require("node:child_process");
const crypto = require("node:crypto");
const fsp = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const zlib = require("node:zlib");

const { getBinarySpec, getVendorBinaryPath } = require("./targets.cjs");

const MAX_COMPRESSED_TARBALL_BYTES = 64 * 1024 * 1024;
const MAX_DECOMPRESSED_TAR_BYTES = 128 * 1024 * 1024;
const MAX_NPM_OUTPUT_BYTES = 4 * 1024 * 1024;
const DEFAULT_TOTAL_TIMEOUT_MS = 300_000;

function getPackageRoot(rootDir = __dirname) {
  return path.resolve(rootDir, "..");
}

function sha256(buffer) {
  return crypto.createHash("sha256").update(buffer).digest("hex");
}

function getNpmInvocation(env, platform = process.platform) {
  const npmExecPath = env.npm_execpath;
  if (typeof npmExecPath === "string" && path.basename(npmExecPath).toLowerCase() === "npm-cli.js") {
    return {
      command: env.npm_node_execpath || process.execPath,
      prefixArgs: [npmExecPath],
      shell: false
    };
  }
  if (platform === "win32") {
    return {
      command: env.ComSpec || "cmd.exe",
      prefixArgs: ["/d", "/s", "/c", "npm"],
      shell: false
    };
  }
  return { command: "npm", prefixArgs: [], shell: false };
}

function runNpm(args, options = {}) {
  const env = {
    ...(options.env || process.env),
    npm_config_update_notifier: "false"
  };
  if (options.runNpmImpl) {
    return options.runNpmImpl(args, { cwd: options.cwd, env });
  }

  const invocation = getNpmInvocation(env, options.platform);
  const maxOutputBytes = options.maxNpmOutputBytes ?? MAX_NPM_OUTPUT_BYTES;
  const timeoutMs = options.npmTimeoutMs ?? DEFAULT_TOTAL_TIMEOUT_MS;

  return new Promise((resolve, reject) => {
    const child = spawn(invocation.command, [...invocation.prefixArgs, ...args], {
      cwd: options.cwd,
      env,
      shell: invocation.shell,
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true
    });
    const stdout = [];
    const stderr = [];
    let outputBytes = 0;
    let settled = false;

    const finish = (error, result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (error) {
        reject(error);
      } else {
        resolve(result);
      }
    };
    const append = (target, chunk) => {
      outputBytes += chunk.length;
      if (outputBytes > maxOutputBytes) {
        child.kill();
        finish(new Error(`npm output exceeded ${maxOutputBytes} bytes`));
        return;
      }
      target.push(chunk);
    };

    child.stdout.on("data", (chunk) => append(stdout, chunk));
    child.stderr.on("data", (chunk) => append(stderr, chunk));
    child.once("error", (error) => finish(new Error(`Could not start npm: ${error.message}`)));
    child.once("close", (code, signal) => {
      if (settled) return;
      const stdoutText = Buffer.concat(stdout).toString("utf8");
      const stderrText = Buffer.concat(stderr).toString("utf8");
      if (code !== 0) {
        const detail = stderrText.trim() || stdoutText.trim();
        finish(new Error(`npm pack failed with ${signal || `status ${code}`}${detail ? `:\n${detail}` : ""}`));
        return;
      }
      finish(null, { stdout: stdoutText, stderr: stderrText });
    });

    const timer = setTimeout(() => {
      child.kill();
      finish(new Error(`npm pack timed out after ${timeoutMs}ms`));
    }, timeoutMs);
    timer.unref?.();
  });
}

function parseNpmPackResult(stdout, spec, version) {
  let records;
  try {
    records = JSON.parse(stdout);
  } catch (error) {
    throw new Error(`npm returned invalid JSON for ${spec.packageName}@${version}`, { cause: error });
  }

  const metadata = Array.isArray(records) && records.length === 1 ? records[0] : null;
  if (
    metadata?.name !== spec.packageName ||
    metadata?.version !== version ||
    typeof metadata?.filename !== "string" ||
    !metadata.filename ||
    typeof metadata?.integrity !== "string" ||
    !metadata.integrity
  ) {
    throw new Error(`npm returned invalid package metadata for ${spec.packageName}@${version}`);
  }
  if (path.basename(metadata.filename) !== metadata.filename) {
    throw new Error(`npm returned an unsafe tarball filename for ${spec.packageName}@${version}`);
  }
  return metadata;
}

async function downloadPackageTarball(spec, version, options = {}) {
  if (!/^[0-9A-Za-z][0-9A-Za-z.+-]*$/.test(version)) {
    throw new Error(`Invalid package version: ${version}`);
  }

  const tempDir = await fsp.mkdtemp(path.join(os.tmpdir(), "agent-dump-npm-pack-"));
  try {
    const env = {
      ...(options.env || process.env),
      npm_config_pack_destination: tempDir
    };
    const npmConfigDirectory = options.npmConfigDirectory || env.npm_config_local_prefix || env.INIT_CWD;
    const result = await runNpm(["pack", `${spec.packageName}@${version}`, "--json", "--ignore-scripts"], {
      ...options,
      cwd: npmConfigDirectory,
      env
    });
    const metadata = parseNpmPackResult(result.stdout, spec, version);
    const tarballPath = path.join(tempDir, metadata.filename);
    const stats = await fsp.stat(tarballPath);
    const maxTarballBytes = options.maxTarballBytes ?? MAX_COMPRESSED_TARBALL_BYTES;
    if (!stats.isFile() || stats.size > maxTarballBytes) {
      throw new Error(`Package tarball for ${spec.packageName}@${version} exceeds ${maxTarballBytes} bytes`);
    }
    return await fsp.readFile(tarballPath);
  } finally {
    await fsp.rm(tempDir, { recursive: true, force: true });
  }
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
    tarballBuffer = await downloadPackageTarball(spec, version, { ...options, env });
  }

  const binaryBuffer = extractBinaryFromTarball(tarballBuffer, spec, options);
  const actualChecksum = sha256(binaryBuffer);

  if (actualChecksum !== expectedChecksum) {
    throw new Error(
      `Checksum mismatch for ${spec.packageName}@${version}: expected ${expectedChecksum}, got ${actualChecksum}`
    );
  }

  const vendorPath = getVendorBinaryPath(packageRoot, spec);
  await publishBinaryAtomically(vendorPath, binaryBuffer);
  return vendorPath;
}

async function publishBinaryAtomically(vendorPath, binaryBuffer) {
  await fsp.mkdir(path.dirname(vendorPath), { recursive: true });

  // 同目录的唯一临时文件 + rename。直接写最终路径的话，一次中断或两个并发
  // installer 就会留下截断/零字节文件，而此后每次启动都会把它当成已安装。
  // 临时文件必须与目标同目录：跨设备 rename 不是原子的。
  const tempPath = `${vendorPath}.${process.pid}-${crypto.randomBytes(6).toString("hex")}.tmp`;

  try {
    const handle = await fsp.open(tempPath, "w", 0o755);
    try {
      await handle.writeFile(binaryBuffer);
      // rename 只保证目录项被原子替换，不保证内容已落盘
      await handle.sync();
    } finally {
      await handle.close();
    }

    if (!vendorPath.endsWith(".exe")) {
      await fsp.chmod(tempPath, 0o755);
    }

    // 刻意不先 unlink 最终路径：那样会留出一个「什么都没有」的窗口，而且失败后
    // 连旧的完整 binary 都没了
    await fsp.rename(tempPath, vendorPath);
  } catch (error) {
    await fsp.rm(tempPath, { force: true });
    if (error.code === "EPERM" || error.code === "EBUSY") {
      // Windows 上正在运行的 binary 会锁住目标；旧文件仍然完好，说清楚即可
      throw new Error(
        `Could not replace ${vendorPath} because it is in use; close any running agent-dump and retry`
      );
    }
    throw error;
  }

  return vendorPath;
}

async function isVendoredBinaryValid(vendorPath, options = {}) {
  const spec = options.spec;
  const packageRoot = options.packageRoot;

  try {
    const version = options.version || (await readPackageVersion(packageRoot, options));
    const checksums = options.checksums || (await readChecksums(packageRoot, options));
    const expectedChecksum = checksums?.[version]?.[spec.target];
    if (!expectedChecksum) {
      return false;
    }
    return sha256(await fsp.readFile(vendorPath)) === expectedChecksum;
  } catch {
    // 读不出来、清单缺失、版本对不上——都当作「需要重装」，而不是接受现状
    return false;
  }
}

async function ensureBinary(options = {}) {
  const platform = options.platform || process.platform;
  const arch = options.arch || process.arch;
  const packageRoot = options.packageRoot || getPackageRoot();
  const spec = options.spec || getBinarySpec(platform, arch);

  const vendorPath = getVendorBinaryPath(packageRoot, spec);

  // 仅凭存在就接受，会让中断或并发留下的截断/零字节文件在之后每次启动被永久当成
  // 已安装；bundled checksum 是判断「装好了」的唯一依据
  if (
    isBinaryInstalled({ ...options, platform, arch, packageRoot, spec }) &&
    (await isVendoredBinaryValid(vendorPath, { ...options, packageRoot, spec }))
  ) {
    return vendorPath;
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
  DEFAULT_TOTAL_TIMEOUT_MS,
  MAX_COMPRESSED_TARBALL_BYTES,
  MAX_DECOMPRESSED_TAR_BYTES,
  MAX_NPM_OUTPUT_BYTES,
  downloadPackageTarball,
  ensureBinary,
  extractBinaryFromTarball,
  getNpmInvocation,
  getPackageRoot,
  getVendorBinaryPath,
  installBinary,
  installBinaryFromPackage,
  isBinaryInstalled,
  isVendoredBinaryValid,
  publishBinaryAtomically,
  parseTarEntries,
  readChecksums,
  runNpm,
  sha256
};

if (require.main === module) {
  installBinaryFromPackage();
}
