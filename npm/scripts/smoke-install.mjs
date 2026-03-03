import { mkdir, rm, symlink } from "node:fs/promises";
import { existsSync } from "node:fs";
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
  const result = spawnSync(command, args, {
    stdio: "inherit",
    encoding: "utf8",
    env: {
      ...process.env,
      npm_config_cache: path.resolve(npmRoot, ".npm-cache"),
      ...options.env
    },
    ...options
  });
  if (result.status !== 0) {
    throw new Error(`${command} ${args.join(" ")} failed with status ${result.status ?? "unknown"}`);
  }
}

const currentWorkspace = currentTargetMap[`${process.platform}:${process.arch}`];
if (!currentWorkspace) {
  throw new Error(`Smoke test is not supported on ${process.platform}/${process.arch}`);
}

run("node", ["./scripts/sync-version.mjs"], { cwd: npmRoot });
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

try {
  const scopeDir = path.resolve(npmRoot, "node_modules", "@agent-dump");
  await mkdir(scopeDir, { recursive: true });
  await symlink(path.resolve(npmRoot, "packages", "cli"), path.resolve(scopeDir, "cli"), process.platform === "win32" ? "junction" : "dir");
  await symlink(
    path.resolve(npmRoot, "packages", currentWorkspace.replace("@agent-dump/", "")),
    path.resolve(scopeDir, currentWorkspace.replace("@agent-dump/cli-", "cli-")),
    process.platform === "win32" ? "junction" : "dir"
  );
  run("node", ["./packages/cli/bin/agent-dump.cjs", "--help"], { cwd: npmRoot });
} finally {
  await rm(path.resolve(npmRoot, "node_modules"), { recursive: true, force: true });
  await rm(path.resolve(npmRoot, "package-lock.json"), { force: true });
}
