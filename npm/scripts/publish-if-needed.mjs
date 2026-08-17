import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";

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

export function publishPackageIfNeeded(packageDir, options = {}) {
  const run = options.run ?? runNpm;
  const log = options.log ?? console.log;
  const local = readLocalMetadata(packageDir, run);
  const packageSpec = `${local.name}@${local.version}`;
  const remoteIntegrity = readRemoteIntegrity(local.name, local.version, run);

  if (remoteIntegrity === local.integrity) {
    log(`Skipping ${packageSpec}: the registry already has the identical tarball.`);
    return PublishOutcome.SKIPPED;
  }
  if (remoteIntegrity !== null) {
    throw new Error(`${packageSpec} already exists with different contents`);
  }

  const published = run(["publish", packageDir, "--provenance", "--access", "public"]);
  if (published.status === 0) {
    emitOutput(published);
    return PublishOutcome.PUBLISHED;
  }
  if (published.error) {
    throw commandError(`Could not publish ${packageSpec}`, published);
  }

  const racedIntegrity = readRemoteIntegrity(local.name, local.version, run);
  if (racedIntegrity === local.integrity) {
    log(`Recovered ${packageSpec}: an identical concurrent publish completed first.`);
    return PublishOutcome.RECOVERED;
  }
  throw commandError(`Could not publish ${packageSpec}`, published);
}

export function main(packageDirs = process.argv.slice(2)) {
  if (packageDirs.length === 0) {
    throw new Error("Usage: publish-if-needed.mjs <package-dir> [<package-dir> ...]");
  }
  for (const packageDir of packageDirs) {
    publishPackageIfNeeded(packageDir);
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    main();
  } catch (error) {
    console.error(error instanceof Error ? error.message : error);
    process.exitCode = 1;
  }
}
