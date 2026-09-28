import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";

import { generateDistribution } from "../scripts/distribution.mjs";
import { NATIVE_TARGETS } from "../scripts/native-targets.mjs";

test("distribution channels use verified release binaries and reject tampering", async (t) => {
  const root = await mkdtemp(path.join(tmpdir(), "agent-dump-distribution-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const version = "1.0.0";
  const checksums = {};
  for (const target of NATIVE_TARGETS) {
    await writeFile(path.join(root, target.releaseAssetName), target.target);
    checksums[target.target] = createHash("sha256").update(target.target).digest("hex");
  }
  await writeFile(path.join(root, "agent-dump-binary-checksums.json"), JSON.stringify({ [version]: checksums }));
  const output = path.join(root, "output");
  await generateDistribution(root, output, version);
  const sums = await readFile(path.join(output, "SHA256SUMS"), "utf8");
  for (const target of NATIVE_TARGETS) {
    assert.ok(sums.includes(`${checksums[target.target]}  ${target.releaseAssetName}\n`));
  }
  const formula = await readFile(path.join(output, "agent-dump.rb"), "utf8");
  for (const target of NATIVE_TARGETS.filter((target) => target.platform !== "win32")) {
    assert.ok(formula.includes(`/v${version}/${target.releaseAssetName}`));
    assert.ok(formula.includes(checksums[target.target]));
  }
  const scoop = JSON.parse(await readFile(path.join(output, "agent-dump.json"), "utf8"));
  assert.equal(scoop.architecture["64bit"].hash, checksums["win32-x64"]);
  assert.equal(scoop.architecture["64bit"].url, `https://github.com/xingkaixin/agent-dump/releases/download/v${version}/agent-dump-win32-x64.exe#/agent-dump.exe`);
  assert.equal(scoop.bin, "agent-dump.exe");
  await assert.rejects(generateDistribution(root, output, "1.0.1"), /Checksum mismatch/);
  await writeFile(path.join(root, NATIVE_TARGETS[0].releaseAssetName), "corrupt");
  await assert.rejects(generateDistribution(root, output, version), /Checksum mismatch/);
});
