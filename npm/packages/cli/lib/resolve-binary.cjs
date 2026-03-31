const fs = require("node:fs");
const path = require("node:path");

const { RELEASES_URL, SUPPORTED_TARGETS, getBinarySpec } = require("./targets.cjs");

function getVendorBinaryPath(spec, options = {}) {
  const packageRoot = options.packageRoot || path.resolve(__dirname, "..");
  return path.join(packageRoot, "vendor", spec.target, spec.executableName);
}

function resolveInstalledBinary(spec, options = {}) {
  const existsSync = options.existsSync || fs.existsSync;
  const binaryPath = getVendorBinaryPath(spec, options);

  if (!existsSync(binaryPath)) {
    throw new Error(`Binary file is missing for ${spec.target}: ${binaryPath}. Reinstall @agent-dump/cli.`);
  }

  return binaryPath;
}

function resolveBinary(options = {}) {
  const spec = getBinarySpec(options.platform, options.arch);
  return resolveInstalledBinary(spec, options);
}

module.exports = {
  RELEASES_URL,
  SUPPORTED_TARGETS,
  getBinarySpec,
  getVendorBinaryPath,
  resolveInstalledBinary,
  resolveBinary
};
