import { readFile, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { NATIVE_TARGETS, getNativeTarget } from "./native-targets.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..", "..");
const npmRoot = path.resolve(repoRoot, "npm");

const versionFile = path.resolve(repoRoot, "src", "agent_dump", "__about__.py");
const outputFile = path.resolve(npmRoot, "packages", "cli", "lib", "binary-checksums.json");

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
const selectedTargets = requestedTargets.length > 0 ? requestedTargets : NATIVE_TARGETS.map((target) => target.target);
const version = parseVersion(await readFile(versionFile, "utf8"));
const checksums = {};

for (const target of selectedTargets) {
  const buffer = await readFile(getNativeTarget(target).binaryPath);
  checksums[target] = sha256(buffer);
}

await writeFile(outputFile, `${JSON.stringify({ [version]: checksums }, null, 2)}\n`, "utf8");
console.log(`Wrote binary checksums for ${version} (${selectedTargets.join(", ")}) to ${outputFile}`);
