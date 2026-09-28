import { chmod, copyFile, mkdir, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { NATIVE_TARGETS } from "./native-targets.mjs";
import { generateDistribution } from "./distribution.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const npmRoot = path.resolve(__dirname, "..");
const checksumPath = path.resolve(npmRoot, "packages", "cli", "lib", "binary-checksums.json");

export async function stageReleaseAssets(outputDirectory) {
  const outputDir = path.resolve(outputDirectory);
  await mkdir(outputDir, { recursive: true });

  for (const target of NATIVE_TARGETS) {
    const outputPath = path.join(outputDir, target.releaseAssetName);
    await copyFile(target.binaryPath, outputPath);
    if (target.platform !== "win32") {
      await chmod(outputPath, 0o755);
    }
  }

  await copyFile(checksumPath, path.join(outputDir, "agent-dump-binary-checksums.json"));
  const { version } = JSON.parse(await readFile(path.join(npmRoot, "packages/cli/package.json"), "utf8"));
  await generateDistribution(outputDir, outputDir, version);
  await copyFile(path.resolve(npmRoot, "../scripts/install.sh"), path.join(outputDir, "install.sh"));
}

async function main(args = process.argv.slice(2)) {
  if (args.length !== 1) {
    throw new Error("Usage: node ./scripts/stage-release-assets.mjs <output-directory>");
  }
  await stageReleaseAssets(args[0]);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await main();
}
