const fs = require("node:fs");
const path = require("node:path");

const { RELEASES_URL, SUPPORTED_TARGETS, getBinarySpec, getVendorBinaryPath } = require("./targets.cjs");

class BinaryMissingError extends Error {
  constructor(target, binaryPath) {
    super(`Binary file is missing for ${target}: ${binaryPath}. Reinstall @agent-dump/cli.`);
    this.name = "BinaryMissingError";
  }
}

function resolveInstalledBinary(spec, options = {}) {
  const existsSync = options.existsSync || fs.existsSync;
  const packageRoot = options.packageRoot || path.resolve(__dirname, "..");
  const binaryPath = getVendorBinaryPath(packageRoot, spec);

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
