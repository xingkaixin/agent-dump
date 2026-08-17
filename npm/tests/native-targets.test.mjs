import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { NATIVE_TARGETS, nativeMatrix, packageTarballName } from "../scripts/native-targets.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..", "..");

test("native target manifest contains complete unique identities", () => {
  assert.ok(NATIVE_TARGETS.length > 0);
  assert.equal(new Set(NATIVE_TARGETS.map((target) => target.target)).size, NATIVE_TARGETS.length);
  assert.equal(
    new Set(NATIVE_TARGETS.map((target) => `${target.platform}:${target.arch}`)).size,
    NATIVE_TARGETS.length
  );

  for (const target of NATIVE_TARGETS) {
    assert.equal(target.target, `${target.platform}-${target.arch}`);
    assert.equal(target.packageName, `@agent-dump/cli-${target.target}`);
    assert.ok(["ELF", "Mach-O", "PE"].includes(target.binaryFormat));
    assert.ok(target.runner);
  }
});

test("platform package manifests project the native target manifest", async () => {
  for (const target of NATIVE_TARGETS) {
    const packageJson = JSON.parse(await fs.readFile(path.join(target.packageDir, "package.json"), "utf8"));
    assert.equal(packageJson.name, target.packageName);
    assert.deepEqual(packageJson.os, [target.platform]);
    assert.deepEqual(packageJson.cpu, [target.arch]);
    assert.deepEqual(packageJson.files, [`bin/${target.executableName}`]);
  }
});

test("release matrix is derived from the native target manifest", () => {
  assert.deepEqual(nativeMatrix(), {
    include: NATIVE_TARGETS.map((target) => ({
      os: target.runner,
      target: target.target,
      binary_name: target.executableName
    }))
  });
});

test("supported target documentation projects the native target manifest", async () => {
  const documentedTargets = NATIVE_TARGETS.map((target) => target.target);
  const documents = ["README.md", "README_zh.md", "npm/packages/cli/README.md"];

  for (const document of documents) {
    const content = await fs.readFile(path.resolve(repoRoot, document), "utf8");
    const block = content.split("<!-- native-targets:start -->", 2)[1]?.split("<!-- native-targets:end -->", 1)[0];
    assert.ok(block, `${document} has no native target projection`);
    assert.deepEqual(
      [...block.matchAll(/^- `([^`]+)`$/gm)].map((match) => match[1]),
      documentedTargets,
      document
    );
  }
});

test("release consumers do not redefine native target names", async () => {
  const scriptDir = path.resolve(repoRoot, "npm", "scripts");
  const scriptFiles = (await fs.readdir(scriptDir))
    .filter((name) => name.endsWith(".mjs"))
    .map((name) => path.join(scriptDir, name));
  const consumers = [
    ...scriptFiles,
    path.resolve(repoRoot, "npm", "packages", "cli", "lib", "targets.cjs"),
    path.resolve(repoRoot, ".github", "workflows", "release.yml")
  ];

  for (const consumer of consumers) {
    const content = await fs.readFile(consumer, "utf8");
    for (const target of NATIVE_TARGETS) {
      assert.ok(!content.includes(target.target), `${path.relative(repoRoot, consumer)} redefines ${target.target}`);
    }
  }
});

test("npm tarball names are derived from package identity", () => {
  for (const target of NATIVE_TARGETS) {
    assert.equal(packageTarballName(target.packageName, "1.2.3"), `agent-dump-cli-${target.target}-1.2.3.tgz`);
  }
});
