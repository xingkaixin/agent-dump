import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..", "..");
const aboutFile = path.resolve(repoRoot, "src", "agent_dump", "__about__.py");
const webVersionDataFile = path.resolve(repoRoot, "web", "version-data.js");

function parseVersion(source) {
  const match = source.match(/__version__\s*=\s*"([^"]+)"/);
  assert.ok(match, "Could not read Python version from src/agent_dump/__about__.py");
  return match[1];
}

async function loadWebVersionData() {
  const source = await fs.readFile(webVersionDataFile, "utf8");
  const context = { window: {} };
  vm.runInNewContext(source, context);
  return JSON.parse(JSON.stringify(context.window.AGENT_DUMP_WEB_DATA));
}

test("web version data stays aligned with the Python version source", async () => {
  const aboutSource = await fs.readFile(aboutFile, "utf8");
  const version = parseVersion(aboutSource);
  const webData = await loadWebVersionData();

  assert.equal(webData.version, version);
  assert.deepEqual(webData.changelogUrl, {
    en: "https://github.com/xingkaixin/agent-dump/blob/main/CHANGELOG.md",
    zh: "https://github.com/xingkaixin/agent-dump/blob/main/docs/zh/CHANGELOG.md"
  });
});
