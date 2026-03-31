import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const npmRoot = path.resolve(__dirname, "..");

const currentTargetMap = {
  "darwin:x64": "@agent-dump/cli-darwin-x64",
  "darwin:arm64": "@agent-dump/cli-darwin-arm64",
  "linux:x64": "@agent-dump/cli-linux-x64",
  "win32:x64": "@agent-dump/cli-win32-x64"
};

function run(command, args, options = {}) {
  const { env: extraEnv, ...restOptions } = options;
  const cacheDir = path.resolve(npmRoot, ".npm-cache");
  const result = spawnSync(command, args, {
    stdio: restOptions.stdio || "inherit",
    encoding: "utf8",
    env: {
      ...process.env,
      npm_config_cache: cacheDir,
      NPM_CONFIG_CACHE: cacheDir,
      ...extraEnv
    },
    ...restOptions
  });
  if (result.status !== 0) {
    throw new Error(`${command} ${args.join(" ")} failed with status ${result.status ?? "unknown"}`);
  }

  return result.stdout?.trim() || "";
}

const currentWorkspace = currentTargetMap[`${process.platform}:${process.arch}`];
if (!currentWorkspace) {
  throw new Error(`Smoke test is not supported on ${process.platform}/${process.arch}`);
}

const checksumFile = path.resolve(npmRoot, "packages", "cli", "lib", "binary-checksums.json");
const originalChecksumFile = await readFile(checksumFile, "utf8");

run("node", ["./scripts/sync-version.mjs"], { cwd: npmRoot });
run("node", ["./scripts/write-checksums.mjs", currentWorkspace.replace("@agent-dump/cli-", "")], { cwd: npmRoot });
const stagedBinaryPath = path.resolve(
  npmRoot,
  "packages",
  currentWorkspace.replace("@agent-dump/", ""),
  "bin",
  process.platform === "win32" ? "agent-dump.exe" : "agent-dump"
);

if (!existsSync(stagedBinaryPath)) {
  throw new Error(`Expected staged binary at ${stagedBinaryPath}`);
}

const mainPackageJson = JSON.parse(await readFile(path.resolve(npmRoot, "packages", "cli", "package.json"), "utf8"));
const version = mainPackageJson.version;
const packageName = currentWorkspace;

const packOutputDir = path.resolve(npmRoot, ".pack");
await rm(packOutputDir, { recursive: true, force: true });
await mkdir(packOutputDir, { recursive: true });

const cacheArgs = ["--cache", path.resolve(npmRoot, ".npm-cache")];

const platformTarballName = run("npm", [...cacheArgs, "pack", `./packages/${currentWorkspace.replace("@agent-dump/", "")}`, "--pack-destination", packOutputDir], {
  cwd: npmRoot,
  stdio: "pipe"
}).trim();
const mainTarballName = run("npm", [...cacheArgs, "pack", "./packages/cli", "--pack-destination", packOutputDir], {
  cwd: npmRoot,
  stdio: "pipe"
}).trim();
const platformTarballPath = path.join(packOutputDir, platformTarballName);
const mainTarballPath = path.join(packOutputDir, mainTarballName);
let installRoot = null;

try {
  installRoot = await mkdtemp(path.join(os.tmpdir(), "agent-dump-smoke-"));
  run("npm", [...cacheArgs, "install", "--ignore-scripts=false", mainTarballPath], {
    cwd: installRoot,
    env: {
      ...process.env,
      AGENT_DUMP_CLI_TARBALL_PATH: platformTarballPath
    }
  });
  run("node", ["./node_modules/@agent-dump/cli/bin/agent-dump.cjs", "--help"], { cwd: installRoot });
} finally {
  await writeFile(checksumFile, originalChecksumFile, "utf8");
  if (installRoot) {
    await rm(installRoot, { recursive: true, force: true });
  }
  await rm(path.resolve(npmRoot, ".pack"), { recursive: true, force: true });
}
