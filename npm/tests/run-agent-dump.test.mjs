import test from "node:test";
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { getForwardSignals, runCli } = require("../packages/cli/lib/run-agent-dump.cjs");

class FakeProcess extends EventEmitter {
  off(eventName, listener) {
    this.removeListener(eventName, listener);
  }
}

test("runCli forwards argv and exits with the child exit code", async () => {
  const child = new EventEmitter();
  child.kill = () => {};

  const fakeProcess = new FakeProcess();
  let exitCode = null;
  let spawned = null;

  await runCli({
    argv: ["--help"],
    platform: "linux",
    arch: "x64",
    processObject: fakeProcess,
    resolveBinaryImpl: () => "/tmp/agent-dump",
    spawnImpl: (command, args, options) => {
      spawned = { command, args, options };
      return child;
    },
    exit: (code) => {
      exitCode = code;
    }
  });

  child.emit("exit", 3, null);

  assert.deepEqual(spawned, {
    command: "/tmp/agent-dump",
    args: ["--help"],
    options: {
      cwd: process.cwd(),
      env: process.env,
      stdio: "inherit"
    }
  });
  assert.equal(exitCode, 3);
});

test("runCli prints an explicit error for unsupported platforms", async () => {
  const messages = [];
  let exitCode = null;

  const child = await runCli({
    platform: "linux",
    arch: "arm64",
    resolveBinaryImpl: () => {
      throw new Error("Unsupported platform linux/arm64");
    },
    writeError: (message) => {
      messages.push(message);
    },
    exit: (code) => {
      exitCode = code;
    }
  });

  assert.equal(child, null);
  assert.equal(exitCode, 1);
  assert.deepEqual(messages, ["Unsupported platform linux/arm64\n"]);
});

test("runCli installs the binary on demand when the vendored file is missing", async () => {
  const child = new EventEmitter();
  child.kill = () => {};

  let ensured = null;
  let spawned = null;

  await runCli({
    argv: ["--help"],
    platform: "linux",
    arch: "x64",
    resolveBinaryImpl: () => {
      throw new Error("Binary file is missing for linux-x64: /tmp/vendor/agent-dump. Reinstall @agent-dump/cli.");
    },
    ensureBinaryImpl: async ({ platform, arch }) => {
      ensured = { platform, arch };
      return "/tmp/agent-dump";
    },
    spawnImpl: (command, args, options) => {
      spawned = { command, args, options };
      return child;
    }
  });

  child.emit("exit", 0, null);

  assert.deepEqual(ensured, { platform: "linux", arch: "x64" });
  assert.deepEqual(spawned, {
    command: "/tmp/agent-dump",
    args: ["--help"],
    options: {
      cwd: process.cwd(),
      env: process.env,
      stdio: "inherit"
    }
  });
});

test("runCli reports install failures when the binary cannot be recovered", async () => {
  const messages = [];
  let exitCode = null;

  const child = await runCli({
    platform: "linux",
    arch: "x64",
    resolveBinaryImpl: () => {
      throw new Error("Binary file is missing for linux-x64: /tmp/vendor/agent-dump. Reinstall @agent-dump/cli.");
    },
    ensureBinaryImpl: async () => {
      throw new Error("network down");
    },
    writeError: (message) => {
      messages.push(message);
    },
    exit: (code) => {
      exitCode = code;
    }
  });

  assert.equal(child, null);
  assert.equal(exitCode, 1);
  assert.deepEqual(messages, ["Failed to install agent-dump native binary: network down\n"]);
});

test("getForwardSignals keeps SIGBREAK only on Windows", () => {
  assert.deepEqual(getForwardSignals("linux"), ["SIGINT", "SIGTERM", "SIGHUP"]);
  assert.deepEqual(getForwardSignals("win32"), ["SIGINT", "SIGTERM", "SIGBREAK"]);
});
