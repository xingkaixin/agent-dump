import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import test from "node:test";

import { NATIVE_TARGETS } from "../scripts/native-targets.mjs";

test("platform package manifests project the native target manifest", async () => {
  for (const target of NATIVE_TARGETS) {
    const packageJson = JSON.parse(await fs.readFile(path.join(target.packageDir, "package.json"), "utf8"));
    assert.equal(packageJson.name, target.packageName);
    assert.deepEqual(packageJson.os, [target.platform]);
    assert.deepEqual(packageJson.cpu, [target.arch]);
    assert.deepEqual(packageJson.files, [`bin/${target.executableName}`]);
  }
});
