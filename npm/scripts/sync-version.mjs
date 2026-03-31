import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..", "..");
const npmRoot = path.resolve(repoRoot, "npm");
const versionFile = path.resolve(repoRoot, "src", "agent_dump", "__about__.py");

const packageFiles = [
  path.resolve(npmRoot, "package.json"),
  path.resolve(npmRoot, "packages", "cli", "package.json"),
  path.resolve(npmRoot, "packages", "cli-darwin-x64", "package.json"),
  path.resolve(npmRoot, "packages", "cli-darwin-arm64", "package.json"),
  path.resolve(npmRoot, "packages", "cli-linux-x64", "package.json"),
  path.resolve(npmRoot, "packages", "cli-win32-x64", "package.json")
];

function parseVersion(source) {
  const match = source.match(/__version__\s*=\s*"([^"]+)"/);
  if (!match) {
    throw new Error("Could not read Python version from src/agent_dump/__about__.py");
  }
  return match[1];
}

async function readJson(filePath) {
  return JSON.parse(await readFile(filePath, "utf8"));
}

async function writeJson(filePath, value) {
  await writeFile(filePath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

const versionSource = await readFile(versionFile, "utf8");
const version = parseVersion(versionSource);

for (const packageFile of packageFiles) {
  const packageJson = await readJson(packageFile);
  packageJson.version = version;

  if (packageJson.name === "@agent-dump/cli") {
    delete packageJson.optionalDependencies;
  }

  await writeJson(packageFile, packageJson);
}

console.log(`Synced npm workspace version to ${version}`);
