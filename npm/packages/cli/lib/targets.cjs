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

module.exports = {
  RELEASES_URL,
  SUPPORTED_TARGETS,
  TARGETS,
  getBinarySpec
};
