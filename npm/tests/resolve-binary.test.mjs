import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import path from "node:path";

const require = createRequire(import.meta.url);
const {
  RELEASES_URL,
  SUPPORTED_TARGETS,
  getBinarySpec,
  getVendorBinaryPath,
  resolveInstalledBinary
} = require("../packages/cli/lib/resolve-binary.cjs");

test("getBinarySpec returns the expected package metadata for each supported target", () => {
  assert.deepEqual(getBinarySpec("darwin", "x64"), {
    target: "darwin-x64",
    packageName: "@agent-dump/cli-darwin-x64",
    executableName: "agent-dump"
  });
  assert.deepEqual(getBinarySpec("darwin", "arm64"), {
    target: "darwin-arm64",
    packageName: "@agent-dump/cli-darwin-arm64",
    executableName: "agent-dump"
  });
  assert.deepEqual(getBinarySpec("linux", "x64"), {
    target: "linux-x64",
    packageName: "@agent-dump/cli-linux-x64",
    executableName: "agent-dump"
  });
  assert.deepEqual(getBinarySpec("win32", "x64"), {
    target: "win32-x64",
    packageName: "@agent-dump/cli-win32-x64",
    executableName: "agent-dump.exe"
  });
});

test("getBinarySpec rejects unsupported platforms with a release link", () => {
  assert.throws(
    () => getBinarySpec("linux", "arm64"),
    (error) =>
      error instanceof Error &&
      error.message.includes("linux/arm64") &&
      error.message.includes(SUPPORTED_TARGETS.join(", ")) &&
      error.message.includes(RELEASES_URL)
  );
});

test("resolveInstalledBinary resolves the vendored binary path from the main package", () => {
  const spec = getBinarySpec("linux", "x64");
  const packageRoot = path.join("/tmp", "agent-dump", "node_modules", "@agent-dump", "cli");
  const expectedPath = path.join(packageRoot, "vendor", "linux-x64", "agent-dump");
  assert.equal(getVendorBinaryPath(spec, { packageRoot }), expectedPath);

  const binaryPath = resolveInstalledBinary(spec, {
    packageRoot,
    existsSync: (target) => {
      assert.equal(target, expectedPath);
      return true;
    }
  });

  assert.equal(binaryPath, expectedPath);
});
