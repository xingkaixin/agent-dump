import { chmod, copyFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const npmRoot = path.resolve(__dirname, "..");

const targetMap = {
  "darwin-x64": {
    packageDir: path.resolve(npmRoot, "packages", "cli-darwin-x64"),
    outputName: "agent-dump"
  },
  "darwin-arm64": {
    packageDir: path.resolve(npmRoot, "packages", "cli-darwin-arm64"),
    outputName: "agent-dump"
  },
  "linux-x64": {
    packageDir: path.resolve(npmRoot, "packages", "cli-linux-x64"),
    outputName: "agent-dump"
  },
  "win32-x64": {
    packageDir: path.resolve(npmRoot, "packages", "cli-win32-x64"),
    outputName: "agent-dump.exe"
  }
};

const [target, sourcePath] = process.argv.slice(2);

if (!target || !sourcePath) {
  throw new Error("Usage: node ./scripts/stage-binaries.mjs <target> <source-binary-path>");
}

const targetConfig = targetMap[target];
if (!targetConfig) {
  throw new Error(`Unsupported target "${target}"`);
}

const outputDir = path.join(targetConfig.packageDir, "bin");
const outputPath = path.join(outputDir, targetConfig.outputName);

await mkdir(outputDir, { recursive: true });
await copyFile(path.resolve(sourcePath), outputPath);

if (!outputPath.endsWith(".exe")) {
  await chmod(outputPath, 0o755);
}

console.log(`Staged ${target} binary to ${outputPath}`);
