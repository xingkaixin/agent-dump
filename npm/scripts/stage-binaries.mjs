import { chmod, copyFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { NATIVE_TARGETS, getNativeTarget } from "./native-targets.mjs";

export async function stageBinary(targetName, sourcePath) {
  const target = getNativeTarget(targetName);
  const outputDir = path.join(target.packageDir, "bin");
  const outputPath = path.join(outputDir, target.executableName);

  await mkdir(outputDir, { recursive: true });
  await copyFile(path.resolve(sourcePath), outputPath);

  if (target.platform !== "win32") {
    await chmod(outputPath, 0o755);
  }

  console.log(`Staged ${target.target} binary to ${outputPath}`);
  return outputPath;
}

export async function stageArtifactBinaries(artifactsRoot) {
  for (const target of NATIVE_TARGETS) {
    const sourcePath = path.resolve(artifactsRoot, target.artifactName, target.executableName);
    await stageBinary(target.target, sourcePath);
  }
}

async function main(args = process.argv.slice(2)) {
  if (args.length === 2 && args[0] === "--artifacts") {
    await stageArtifactBinaries(args[1]);
    return;
  }
  if (args.length === 2) {
    await stageBinary(args[0], args[1]);
    return;
  }
  throw new Error(
    "Usage: node ./scripts/stage-binaries.mjs <target> <source-binary-path> | --artifacts <download-root>"
  );
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await main();
}
