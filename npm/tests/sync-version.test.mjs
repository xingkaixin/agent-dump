import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { NATIVE_TARGETS } from "../scripts/native-targets.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..", "..");
const aboutFile = path.resolve(repoRoot, "src", "agent_dump", "__about__.py");

function parseVersion(source) {
  const match = source.match(/__version__\s*=\s*"([^"]+)"/);
  assert.ok(match, "Could not read Python version from src/agent_dump/__about__.py");
  return match[1];
}

const npmRoot = path.resolve(repoRoot, "npm");
const packageFiles = [
  path.resolve(npmRoot, "package.json"),
  path.resolve(npmRoot, "packages", "cli", "package.json"),
  ...NATIVE_TARGETS.map((target) => path.resolve(target.packageDir, "package.json"))
];

test("npm workspace versions stay aligned with the Python version source", async () => {
  const version = parseVersion(await fs.readFile(aboutFile, "utf8"));
  for (const file of packageFiles) {
    const pkg = JSON.parse(await fs.readFile(file, "utf8"));
    assert.equal(pkg.version, version, `${path.relative(repoRoot, file)} is out of sync`);
  }
});
