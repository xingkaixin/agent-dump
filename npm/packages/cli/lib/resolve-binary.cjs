const fs = require("node:fs");
const path = require("node:path");

const TARGETS = {
  "darwin:x64": {
    target: "darwin-x64",
    packageName: "@agent-dump/cli-darwin-x64",
    executableName: "agent-dump"
  },
  "darwin:arm64": {
    target: "darwin-arm64",
    packageName: "@agent-dump/cli-darwin-arm64",
    executableName: "agent-dump"
  },
  "linux:x64": {
    target: "linux-x64",
    packageName: "@agent-dump/cli-linux-x64",
    executableName: "agent-dump"
  },
  "win32:x64": {
    target: "win32-x64",
    packageName: "@agent-dump/cli-win32-x64",
    executableName: "agent-dump.exe"
  }
};

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

function resolveInstalledBinary(spec, options = {}) {
  const requireResolve = options.requireResolve || require.resolve;
  const existsSync = options.existsSync || fs.existsSync;
  const packageJsonPath = requireResolve(`${spec.packageName}/package.json`);
  const binaryPath = path.join(path.dirname(packageJsonPath), "bin", spec.executableName);

  if (!existsSync(binaryPath)) {
    throw new Error(`Binary file is missing for ${spec.target}: ${binaryPath}`);
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
  resolveInstalledBinary,
  resolveBinary
};
