import { createRequire } from "node:module";
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  readLocalMetadata,
  readRemoteIntegrity,
  requireSuccessJson,
  runNpm
} from "./publish-if-needed.mjs";
import { NATIVE_TARGETS } from "./native-targets.mjs";

const require = createRequire(import.meta.url);
const { extractBinaryFromTarball } = require("../packages/cli/lib/install-binary.cjs");

export const RestoreOutcome = Object.freeze({
  UNPUBLISHED: "unpublished",
  UNCHANGED: "unchanged",
  RESTORED: "restored"
});

function downloadPublishedTarball(packageSpec, expectedIntegrity, tempDir, run) {
  const records = requireSuccessJson(
    run([
      "pack",
      packageSpec,
      "--json",
      "--pack-destination",
      tempDir,
      "--ignore-scripts",
      "--prefer-online"
    ]),
    `Could not download ${packageSpec}`
  );
  const metadata = Array.isArray(records) ? records[0] : undefined;
  if (!metadata?.filename || metadata.integrity !== expectedIntegrity || records.length !== 1) {
    throw new Error(`Downloaded tarball integrity does not match the registry metadata for ${packageSpec}`);
  }
  if (path.basename(metadata.filename) !== metadata.filename) {
    throw new Error(`npm returned an unsafe tarball filename for ${packageSpec}`);
  }
  return path.join(tempDir, metadata.filename);
}

export function restorePublishedBinary(packageDir, executableName, options = {}) {
  const run = options.run ?? runNpm;
  const log = options.log ?? console.log;
  const local = readLocalMetadata(packageDir, run);
  const packageSpec = `${local.name}@${local.version}`;
  const remoteIntegrity = readRemoteIntegrity(local.name, local.version, run);
  if (remoteIntegrity === null) {
    return RestoreOutcome.UNPUBLISHED;
  }
  if (remoteIntegrity === local.integrity) {
    return RestoreOutcome.UNCHANGED;
  }

  const tempDir = mkdtempSync(path.join(os.tmpdir(), "agent-dump-release-"));
  try {
    const tarballPath = downloadPublishedTarball(packageSpec, remoteIntegrity, tempDir, run);
    const binary = extractBinaryFromTarball(readFileSync(tarballPath), {
      packageName: local.name,
      executableName
    });
    const outputPath = path.join(packageDir, "bin", executableName);
    mkdirSync(path.dirname(outputPath), { recursive: true });
    writeFileSync(outputPath, binary);
    if (!outputPath.endsWith(".exe")) {
      chmodSync(outputPath, 0o755);
    }

    const restored = readLocalMetadata(packageDir, run);
    if (restored.integrity !== remoteIntegrity) {
      throw new Error(`${packageSpec} cannot be reconstructed from its published binary and current manifest`);
    }
    log(`Restored published binary for ${packageSpec}.`);
    return RestoreOutcome.RESTORED;
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
}

export function main() {
  for (const { packageDir, executableName } of NATIVE_TARGETS) {
    restorePublishedBinary(packageDir, executableName);
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
