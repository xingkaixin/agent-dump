import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

import { NATIVE_TARGETS } from "../scripts/native-targets.mjs";

const require = createRequire(import.meta.url);
const { SUPPORTED_TARGETS, getBinarySpec } = require("../packages/cli/lib/resolve-binary.cjs");

test("getBinarySpec returns the expected package metadata for each supported target", () => {
  for (const target of NATIVE_TARGETS) {
    assert.deepEqual(getBinarySpec(target.platform, target.arch), {
      target: target.target,
      packageName: target.packageName,
      executableName: target.executableName
    });
  }
  assert.deepEqual(SUPPORTED_TARGETS, NATIVE_TARGETS.map((target) => target.target));
});
