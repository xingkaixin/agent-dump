import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { setTimeout } from "node:timers/promises";
import { fileURLToPath } from "node:url";

import { NATIVE_TARGETS, packageTarballName } from "./native-targets.mjs";

const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const npmRoot = path.resolve(__dirname, "..");

export const PublishOutcome = Object.freeze({
  PUBLISHED: "published",
  SKIPPED: "skipped",
  RECOVERED: "recovered"
});

export function runNpm(args) {
  return spawnSync(npmCommand, args, {
    encoding: "utf8",
    env: process.env,
    maxBuffer: 20 * 1024 * 1024
  });
}

function commandError(context, result) {
  if (result.error) {
    return new Error(`${context}: ${result.error.message}`);
  }
  const detail = [result.stdout, result.stderr].filter(Boolean).join("\n").trim();
  return new Error(`${context}${detail ? `:\n${detail}` : ""}`);
}

export function requireSuccessJson(result, context) {
  if (result.status !== 0) {
    throw commandError(context, result);
  }
  try {
    return JSON.parse(result.stdout);
  } catch (error) {
    throw new Error(`${context}: npm returned invalid JSON`, { cause: error });
  }
}

export function readLocalMetadata(packageDir, run) {
  const records = requireSuccessJson(
    run(["pack", packageDir, "--json", "--dry-run"]),
    `Could not pack ${packageDir}`
  );
  const metadata = Array.isArray(records) ? records[0] : undefined;
  if (!metadata?.name || !metadata?.version || !metadata?.integrity || records.length !== 1) {
    throw new Error(`Could not determine package identity and integrity for ${packageDir}`);
  }
  return metadata;
}

export function readRemoteIntegrity(name, version, run) {
  const result = run(["view", `${name}@${version}`, "dist.integrity", "--json", "--prefer-online"]);
  if (result.status === 0) {
    const integrity = requireSuccessJson(result, `Could not inspect ${name}@${version}`);
    if (typeof integrity !== "string" || !integrity) {
      throw new Error(`Registry returned no integrity for ${name}@${version}`);
    }
    return integrity;
  }

  try {
    const payload = JSON.parse(result.stdout);
    if (payload?.error?.code === "E404") {
      return null;
    }
  } catch {
    // The original command output below is more useful than a secondary JSON parse failure.
  }
  throw commandError(`Could not inspect ${name}@${version}`, result);
}

function emitOutput(result) {
  if (result.stdout) {
    process.stdout.write(result.stdout);
  }
  if (result.stderr) {
    process.stderr.write(result.stderr);
  }
}

/**
 * @param {{ name: string, version: string, integrity: string }[]} packages
 * @param {{ run?: typeof runNpm, log?: typeof console.log, wait?: typeof setTimeout }} options
 * @returns {Promise<void>}
 */
async function waitForPublishedPackages(packages, options) {
  const run = options.run ?? runNpm;
  const log = options.log ?? console.log;
  const wait = options.wait ?? setTimeout;
  const attempts = 40;
  let pending = packages;

  for (let attempt = 1; pending.length > 0; attempt += 1) {
    const unavailable = [];
    for (const local of pending) {
      const packageSpec = `${local.name}@${local.version}`;
      log(`Checking download availability for ${packageSpec} (${attempt}/${attempts}).`);
      const result = run([
        "pack", packageSpec, "--json", "--dry-run", "--ignore-scripts", "--prefer-online",
        "--fetch-retries=0", "--fetch-timeout=15000"
      ]);
      if (result.status === 0) {
        const records = requireSuccessJson(result, `Could not download ${packageSpec}`);
        const remote = Array.isArray(records) && records.length === 1 ? records[0] : undefined;
        if (remote?.name !== local.name || remote?.version !== local.version || remote?.integrity !== local.integrity) {
          throw new Error(`Downloaded package does not match the release tarball for ${packageSpec}`);
        }
        log(`Verified ${packageSpec}: the published tarball is downloadable and identical.`);
        continue;
      }

      let errorCode;
      try {
        errorCode = JSON.parse(result.stdout)?.error?.code;
      } catch {
        throw commandError(`Could not check download availability for ${packageSpec}`, result);
      }
      if (result.error || !["E404", "ETARGET"].includes(errorCode)) {
        throw commandError(`Could not check download availability for ${packageSpec}`, result);
      }
      if (attempt === attempts) {
        throw commandError(`${packageSpec} is still unavailable after ${attempts} checks`, result);
      }
      log(`${packageSpec} is not available yet (${errorCode}).`);
      unavailable.push(local);
    }
    pending = unavailable;
    if (pending.length > 0) {
      log("Retrying in 15 seconds.");
      await wait(15_000);
    }
  }
}

function publishPackage(packageDir, options) {
  const run = options.run ?? runNpm;
  const log = options.log ?? console.log;
  const local = readLocalMetadata(packageDir, run);
  const packageSpec = `${local.name}@${local.version}`;
  const remoteIntegrity = readRemoteIntegrity(local.name, local.version, run);

  if (remoteIntegrity === local.integrity) {
    log(`Skipping ${packageSpec}: the registry already has the identical tarball.`);
    return { local, outcome: PublishOutcome.SKIPPED };
  }
  if (remoteIntegrity !== null) {
    throw new Error(`${packageSpec} already exists with different contents`);
  }

  const published = run(["publish", packageDir, "--provenance", "--access", "public"]);
  if (published.status === 0) {
    emitOutput(published);
    return { local, outcome: PublishOutcome.PUBLISHED };
  }
  if (published.error) {
    throw commandError(`Could not publish ${packageSpec}`, published);
  }

  const racedIntegrity = readRemoteIntegrity(local.name, local.version, run);
  if (racedIntegrity === local.integrity) {
    log(`Recovered ${packageSpec}: an identical concurrent publish completed first.`);
    return { local, outcome: PublishOutcome.RECOVERED };
  }
  throw commandError(`Could not publish ${packageSpec}`, published);
}

export async function publishPackageIfNeeded(packageDir, options = {}) {
  const { local, outcome } = publishPackage(packageDir, options);
  await waitForPublishedPackages([local], options);
  return outcome;
}

export function releaseTarballPaths(releaseDir) {
  const wrapperManifest = JSON.parse(readFileSync(path.resolve(npmRoot, "packages", "cli", "package.json"), "utf8"));
  const outputDir = path.resolve(releaseDir);
  return [
    ...NATIVE_TARGETS.map((target) =>
      path.join(outputDir, packageTarballName(target.packageName, wrapperManifest.version))
    ),
    path.join(outputDir, packageTarballName(wrapperManifest.name, wrapperManifest.version))
  ];
}

function resolvePackageDirs(args) {
  if (args[0] !== "--release-dir") {
    return args;
  }
  if (args.length !== 2) {
    throw new Error("Usage: publish-if-needed.mjs --release-dir <packed-tarball-directory>");
  }
  return releaseTarballPaths(args[1]);
}

export async function main(args = process.argv.slice(2), options = {}) {
  const packageDirs = resolvePackageDirs(args);
  if (packageDirs.length === 0) {
    throw new Error("Usage: publish-if-needed.mjs <package-path> [<package-path> ...]");
  }
  // registry 处理每个包要 1.5 到 5 分钟，逐个等会把一次发布拖到 13 分钟以上，所以原生包
  // 一起等。wrapper 依赖它们，必须等全部可下载后才发布，否则 npx 用户会装到缺失的版本。
  const nativePackages = packageDirs.slice(0, -1).map((packageDir) => publishPackage(packageDir, options));
  await waitForPublishedPackages(nativePackages.map(({ local }) => local), options);
  await publishPackageIfNeeded(packageDirs.at(-1), options);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    await main();
  } catch (error) {
    console.error(error instanceof Error ? error.message : error);
    process.exitCode = 1;
  }
}
