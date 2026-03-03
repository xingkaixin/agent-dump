const os = require("node:os");
const { spawn } = require("node:child_process");

const { resolveBinary } = require("./resolve-binary.cjs");

function getForwardSignals(platform) {
  return platform === "win32" ? ["SIGINT", "SIGTERM", "SIGBREAK"] : ["SIGINT", "SIGTERM", "SIGHUP"];
}

function exitCodeForSignal(signal) {
  const signalNumber = os.constants.signals?.[signal];
  return typeof signalNumber === "number" ? 128 + signalNumber : 1;
}

function attachSignalForwarding(child, signals, processObject) {
  const listeners = signals.map((signal) => {
    const handler = () => {
      if (typeof child.kill !== "function") {
        return;
      }

      try {
        child.kill(signal);
      } catch {
        // Ignore forwarding failures and let the child process finish on its own.
      }
    };

    processObject.on(signal, handler);
    return { signal, handler };
  });

  return () => {
    for (const { signal, handler } of listeners) {
      if (typeof processObject.off === "function") {
        processObject.off(signal, handler);
      } else {
        processObject.removeListener(signal, handler);
      }
    }
  };
}

function runCli(options = {}) {
  const platform = options.platform || process.platform;
  const arch = options.arch || process.arch;
  const argv = options.argv || process.argv.slice(2);
  const spawnImpl = options.spawnImpl || spawn;
  const cwd = options.cwd || process.cwd();
  const env = options.env || process.env;
  const stdio = options.stdio || "inherit";
  const processObject = options.processObject || process;
  const writeError = options.writeError || ((message) => process.stderr.write(message));
  const exit = options.exit || ((code) => {
    process.exitCode = code;
  });
  const resolveBinaryImpl = options.resolveBinaryImpl || resolveBinary;

  let binaryPath;
  try {
    binaryPath = resolveBinaryImpl({ platform, arch });
  } catch (error) {
    writeError(`${error.message}\n`);
    exit(1);
    return null;
  }

  const child = spawnImpl(binaryPath, argv, {
    cwd,
    env,
    stdio
  });

  const cleanup = attachSignalForwarding(child, getForwardSignals(platform), processObject);

  child.once("error", (error) => {
    cleanup();
    writeError(`Failed to start agent-dump binary: ${error.message}\n`);
    exit(1);
  });

  child.once("exit", (code, signal) => {
    cleanup();

    if (signal) {
      exit(exitCodeForSignal(signal));
      return;
    }

    exit(typeof code === "number" ? code : 1);
  });

  return child;
}

module.exports = {
  attachSignalForwarding,
  exitCodeForSignal,
  getForwardSignals,
  runCli
};
