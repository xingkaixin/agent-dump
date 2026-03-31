import { stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const npmRoot = path.resolve(__dirname, "..");

const targets = [
  {
    name: "darwin-x64",
    binaryPath: path.resolve(npmRoot, "packages", "cli-darwin-x64", "bin", "agent-dump"),
    textDisallowed: true
  },
  {
    name: "darwin-arm64",
    binaryPath: path.resolve(npmRoot, "packages", "cli-darwin-arm64", "bin", "agent-dump"),
    textDisallowed: true
  },
  {
    name: "linux-x64",
    binaryPath: path.resolve(npmRoot, "packages", "cli-linux-x64", "bin", "agent-dump"),
    textDisallowed: true
  },
  {
    name: "win32-x64",
    binaryPath: path.resolve(npmRoot, "packages", "cli-win32-x64", "bin", "agent-dump.exe"),
    textDisallowed: false
  }
];

for (const target of targets) {
  const binaryStat = await stat(target.binaryPath);
  if (binaryStat.size <= 0) {
    throw new Error(`Staged binary for ${target.name} is empty: ${target.binaryPath}`);
  }

  if (!target.textDisallowed) {
    continue;
  }

  const result = spawnSync("file", [target.binaryPath], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"]
  });
  if (result.status !== 0) {
    throw new Error(`Failed to inspect staged binary for ${target.name}: ${result.stderr.trim()}`);
  }

  const output = result.stdout.toLowerCase();
  if (output.includes("text")) {
    throw new Error(`Staged binary for ${target.name} is not a native executable: ${result.stdout.trim()}`);
  }
}

console.log(`Validated staged binaries for ${targets.map((target) => target.name).join(", ")}`);
