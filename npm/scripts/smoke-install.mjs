import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import { NATIVE_TARGETS } from "./native-targets.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const npmRoot = path.resolve(__dirname, "..");
const require = createRequire(import.meta.url);
const { getBinarySpec } = require("../packages/cli/lib/targets.cjs");
const { extractBinaryFromTarball } = require("../packages/cli/lib/install-binary.cjs");

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

function parsePackMetadata(output, packageDir) {
  let records;
  try {
    records = JSON.parse(output);
  } catch (error) {
    throw new Error(`npm pack returned invalid JSON for ${packageDir}`, { cause: error });
  }
  if (!Array.isArray(records) || records.length !== 1) {
    const count = Array.isArray(records) ? records.length : "invalid";
    throw new Error(`npm pack returned ${count} records for ${packageDir}`);
  }
  return records[0];
}

function hasExactValues(actual, expected) {
  return (
    Array.isArray(actual) &&
    actual.length === expected.length &&
    actual.every((value, index) => value === expected[index])
  );
}

export function validatePackedPlatformTarball(metadata, manifest, spec, expectedVersion) {
  if (metadata.name !== spec.packageName || manifest.name !== spec.packageName) {
    throw new Error(`Packed ${spec.target} package name does not match ${spec.packageName}`);
  }
  if (metadata.version !== expectedVersion || manifest.version !== expectedVersion) {
    throw new Error(`Packed ${spec.target} package version does not match ${expectedVersion}`);
  }
  if (!hasExactValues(manifest.os, [spec.platform]) || !hasExactValues(manifest.cpu, [spec.arch])) {
    throw new Error(`Packed ${spec.target} package does not declare ${spec.platform}/${spec.arch}`);
  }

  const expectedPath = `bin/${spec.executableName}`;
  const executableEntries = Array.isArray(metadata.files)
    ? metadata.files.filter((file) => file.path.startsWith("bin/"))
    : [];
  if (executableEntries.length !== 1 || executableEntries[0].path !== expectedPath) {
    throw new Error(`Packed ${spec.target} package must contain only ${expectedPath} under bin/`);
  }
  if (!Number.isSafeInteger(executableEntries[0].size) || executableEntries[0].size <= 0) {
    throw new Error(`Packed ${spec.target} executable is empty`);
  }
  const executableMode = executableEntries[0].mode;
  if (spec.platform !== "win32" && (!Number.isSafeInteger(executableMode) || (executableMode & 0o111) === 0)) {
    throw new Error(`Packed ${spec.target} executable is not executable`);
  }
}

function packPackage(packageDir, packOutputDir, cacheArgs) {
  const output = run(
    "npm",
    [...cacheArgs, "pack", packageDir, "--json", "--pack-destination", packOutputDir],
    { cwd: npmRoot, stdio: "pipe" }
  );
  const metadata = parsePackMetadata(output, packageDir);
  const tarballPath = path.resolve(packOutputDir, metadata.filename);
  if (!existsSync(tarballPath)) {
    throw new Error(`npm pack did not create ${tarballPath}`);
  }
  return { metadata, tarballPath };
}

function selectTargetSpecs(args, currentSpec) {
  const knownArgs = new Set(["--all-platforms", "--keep-pack"]);
  const unknownArgs = args.filter((arg) => !knownArgs.has(arg));
  if (unknownArgs.length > 0) {
    throw new Error(`Unknown smoke option: ${unknownArgs.join(", ")}`);
  }
  return args.includes("--all-platforms")
    ? NATIVE_TARGETS
    : NATIVE_TARGETS.filter((spec) => spec.target === currentSpec.target);
}

export async function main(args = process.argv.slice(2)) {
  const currentSpec = getBinarySpec(process.platform, process.arch);
  const selectedSpecs = selectTargetSpecs(args, currentSpec);
  const keepPack = args.includes("--keep-pack");
  const checksumFile = path.resolve(npmRoot, "packages", "cli", "lib", "binary-checksums.json");
  const originalChecksumFile = await readFile(checksumFile, "utf8");
  const packOutputDir = path.resolve(npmRoot, ".pack");
  const cacheArgs = ["--cache", path.resolve(npmRoot, ".npm-cache")];
  let installRoot = null;

  await rm(packOutputDir, { recursive: true, force: true });
  await mkdir(packOutputDir, { recursive: true });

  try {
    run("node", ["./scripts/sync-version.mjs"], { cwd: npmRoot });
    run("node", ["./scripts/write-checksums.mjs", ...selectedSpecs.map((spec) => spec.target)], { cwd: npmRoot });

    const mainPackageJson = JSON.parse(
      await readFile(path.resolve(npmRoot, "packages", "cli", "package.json"), "utf8")
    );
    const platformTarballs = new Map();

    for (const spec of selectedSpecs) {
      const packageDir = spec.packageDir;
      const stagedBinaryPath = spec.binaryPath;
      if (!existsSync(stagedBinaryPath)) {
        throw new Error(`Expected staged binary at ${stagedBinaryPath}`);
      }

      const manifest = JSON.parse(await readFile(path.resolve(packageDir, "package.json"), "utf8"));
      const packed = packPackage(packageDir, packOutputDir, cacheArgs);
      validatePackedPlatformTarball(packed.metadata, manifest, spec, mainPackageJson.version);
      const [stagedBinary, packedTarball] = await Promise.all([
        readFile(stagedBinaryPath),
        readFile(packed.tarballPath)
      ]);
      if (!extractBinaryFromTarball(packedTarball, spec).equals(stagedBinary)) {
        throw new Error(`Packed ${spec.target} executable does not match the staged binary`);
      }
      platformTarballs.set(spec.target, packed.tarballPath);
    }

    const { tarballPath: mainTarballPath } = packPackage(
      path.resolve(npmRoot, "packages", "cli"),
      packOutputDir,
      cacheArgs
    );
    const platformTarballPath = platformTarballs.get(currentSpec.target);
    if (!platformTarballPath) {
      throw new Error(`Packed tarball is missing for current target ${currentSpec.target}`);
    }

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
    if (!keepPack) {
      await rm(packOutputDir, { recursive: true, force: true });
    }
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await main();
}
