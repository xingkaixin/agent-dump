import { readFile, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..", "..");
const npmRoot = path.resolve(repoRoot, "npm");

const versionFile = path.resolve(repoRoot, "src", "agent_dump", "__about__.py");
const outputFile = path.resolve(npmRoot, "packages", "cli", "lib", "binary-checksums.json");

const targetMap = {
  "darwin-x64": path.resolve(npmRoot, "packages", "cli-darwin-x64", "bin", "agent-dump"),
  "darwin-arm64": path.resolve(npmRoot, "packages", "cli-darwin-arm64", "bin", "agent-dump"),
  "linux-x64": path.resolve(npmRoot, "packages", "cli-linux-x64", "bin", "agent-dump"),
  "win32-x64": path.resolve(npmRoot, "packages", "cli-win32-x64", "bin", "agent-dump.exe")
};

function parseVersion(source) {
  const match = source.match(/__version__\s*=\s*"([^"]+)"/);
  if (!match) {
    throw new Error("Could not read Python version from src/agent_dump/__about__.py");
  }

  return match[1];
}

function sha256(buffer) {
  return createHash("sha256").update(buffer).digest("hex");
}

const requestedTargets = process.argv.slice(2);
const selectedTargets = requestedTargets.length > 0 ? requestedTargets : Object.keys(targetMap);
const version = parseVersion(await readFile(versionFile, "utf8"));
const checksums = {};

for (const target of selectedTargets) {
  const binaryPath = targetMap[target];
  if (!binaryPath) {
    throw new Error(`Unsupported checksum target "${target}"`);
  }

  const buffer = await readFile(binaryPath);
  checksums[target] = sha256(buffer);
}

await writeFile(outputFile, `${JSON.stringify({ [version]: checksums }, null, 2)}\n`, "utf8");
console.log(`Wrote binary checksums for ${version} (${selectedTargets.join(", ")}) to ${outputFile}`);
