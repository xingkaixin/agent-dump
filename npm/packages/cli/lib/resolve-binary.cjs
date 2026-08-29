const fs = require("node:fs");
const path = require("node:path");

const { RELEASES_URL, SUPPORTED_TARGETS, getBinarySpec } = require("./targets.cjs");

class BinaryMissingError extends Error {
  constructor(target, binaryPath) {
    super(`Binary file is missing for ${target}: ${binaryPath}. Reinstall @agent-dump/cli.`);
    this.name = "BinaryMissingError";
  }
}

function getVendorBinaryPath(spec, options = {}) {
  const packageRoot = options.packageRoot || path.resolve(__dirname, "..");
  return path.join(packageRoot, "vendor", spec.target, spec.executableName);
}

function resolveInstalledBinary(spec, options = {}) {
  const existsSync = options.existsSync || fs.existsSync;
  const binaryPath = getVendorBinaryPath(spec, options);

  if (!existsSync(binaryPath)) {
    throw new BinaryMissingError(spec.target, binaryPath);
  }

  return binaryPath;
}

function resolveBinary(options = {}) {
  const spec = getBinarySpec(options.platform, options.arch);
  return resolveInstalledBinary(spec, options);
}

module.exports = {
  BinaryMissingError,
  RELEASES_URL,
  SUPPORTED_TARGETS,
  getBinarySpec,
  getVendorBinaryPath,
  resolveInstalledBinary,
  resolveBinary
};
