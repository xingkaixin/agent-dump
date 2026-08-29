const path = require("node:path");

const manifest = require("./native-targets.json");

const TARGETS = {};
for (const { platform, arch, target, packageName, executableName } of manifest) {
  const key = `${platform}:${arch}`;
  if (TARGETS[key]) {
    throw new Error(`Duplicate native platform and architecture: ${key}`);
  }
  TARGETS[key] = Object.freeze({ target, packageName, executableName });
}
Object.freeze(TARGETS);

const SUPPORTED_TARGETS = Object.values(TARGETS).map((target) => target.target);
const RELEASES_URL = "https://github.com/xingkaixin/agent-dump/releases";

function getBinarySpec(platform = process.platform, arch = process.arch) {
  const spec = TARGETS[`${platform}:${arch}`];
  if (spec) {
    return spec;
  }

  throw new Error(
    `Unsupported platform ${platform}/${arch}. Supported targets: ${SUPPORTED_TARGETS.join(", ")}. ` +
      `See ${RELEASES_URL}`
  );
}

function getVendorBinaryPath(packageRoot, spec) {
  return path.join(packageRoot, "vendor", spec.target, spec.executableName);
}

module.exports = {
  RELEASES_URL,
  SUPPORTED_TARGETS,
  TARGETS,
  getBinarySpec,
  getVendorBinaryPath
};
