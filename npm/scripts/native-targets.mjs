import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const manifest = require("../packages/cli/lib/native-targets.json");
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const npmRoot = path.resolve(__dirname, "..");

function packageDirectoryName(packageName) {
  const prefix = "@agent-dump/";
  if (!packageName.startsWith(prefix) || packageName.slice(prefix.length).includes("/")) {
    throw new Error(`Native package name must be under ${prefix}: ${packageName}`);
  }
  return packageName.slice(prefix.length);
}

function enrichTarget(target) {
  const packageDir = path.resolve(npmRoot, "packages", packageDirectoryName(target.packageName));
  const windowsSuffix = target.executableName.endsWith(".exe") ? ".exe" : "";
  return Object.freeze({
    ...target,
    packageDir,
    binaryPath: path.resolve(packageDir, "bin", target.executableName),
    artifactName: `native-${target.target}`,
    releaseAssetName: `agent-dump-${target.target}${windowsSuffix}`
  });
}

export const NATIVE_TARGETS = Object.freeze(manifest.map(enrichTarget));
const targetsByName = new Map(NATIVE_TARGETS.map((target) => [target.target, target]));

if (targetsByName.size !== NATIVE_TARGETS.length) {
  throw new Error("Native target names must be unique");
}

export function getNativeTarget(targetName) {
  const target = targetsByName.get(targetName);
  if (!target) {
    throw new Error(`Unsupported native target "${targetName}"`);
  }
  return target;
}

export function packageTarballName(packageName, version) {
  const normalizedName = packageName.startsWith("@") ? packageName.slice(1).replace("/", "-") : packageName;
  return `${normalizedName}-${version}.tgz`;
}

export function nativeMatrix() {
  return {
    include: NATIVE_TARGETS.map((target) => ({
      os: target.runner,
      target: target.target,
      binary_name: target.executableName
    }))
  };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.stdout.write(`${JSON.stringify(nativeMatrix())}\n`);
}
