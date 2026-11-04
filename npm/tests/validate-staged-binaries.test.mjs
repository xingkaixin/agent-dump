import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import { validateStagedBinary } from "../scripts/validate-staged-binaries.mjs";

// 只构造头部：校验读的就是 magic 与 machine 字段，不需要真的可执行文件
function machO(arch) {
  const buffer = Buffer.alloc(64);
  buffer.writeUInt32LE(0xfeedfacf, 0);
  buffer.writeUInt32LE({ x64: 0x01000007, arm64: 0x0100000c }[arch], 4);
  return buffer;
}

async function writeFixture(t, content) {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "agent-dump-validate-"));
  t.after(() => fs.rm(dir, { recursive: true, force: true }));
  const filePath = path.join(dir, "agent-dump");
  await fs.writeFile(filePath, content);
  return filePath;
}

test("rejects two swapped darwin binaries", async (t) => {
  const armAsIntel = await writeFixture(t, machO("arm64"));
  await assert.rejects(
    validateStagedBinary("darwin-x64", armAsIntel),
    /is Mach-O\/arm64, expected Mach-O\/x64/
  );

  const intelAsArm = await writeFixture(t, machO("x64"));
  await assert.rejects(
    validateStagedBinary("darwin-arm64", intelAsArm),
    /is Mach-O\/x64, expected Mach-O\/arm64/
  );
});
