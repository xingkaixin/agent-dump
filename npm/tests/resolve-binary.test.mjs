import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import path from "node:path";

const require = createRequire(import.meta.url);
const {
  RELEASES_URL,
  SUPPORTED_TARGETS,
  getBinarySpec,
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

test("resolveInstalledBinary resolves the staged binary path from the platform package", () => {
  const spec = getBinarySpec("linux", "x64");
  const binaryPath = resolveInstalledBinary(spec, {
    requireResolve: (request) => {
      assert.equal(request, "@agent-dump/cli-linux-x64/package.json");
      return path.join("/tmp", "agent-dump", "node_modules", "@agent-dump", "cli-linux-x64", "package.json");
    },
    existsSync: (target) => {
      assert.equal(
        target,
        path.join("/tmp", "agent-dump", "node_modules", "@agent-dump", "cli-linux-x64", "bin", "agent-dump")
      );
      return true;
    }
  });

  assert.equal(
    binaryPath,
    path.join("/tmp", "agent-dump", "node_modules", "@agent-dump", "cli-linux-x64", "bin", "agent-dump")
  );
});
