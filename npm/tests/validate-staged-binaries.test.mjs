import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import { STAGED_TARGETS, identifyBinary, validateStagedBinary } from "../scripts/validate-staged-binaries.mjs";

// 只构造头部：校验读的就是 magic 与 machine 字段，不需要真的可执行文件
function elf(machine) {
  const buffer = Buffer.alloc(64);
  buffer.writeUInt32BE(0x7f454c46, 0);
  buffer.writeUInt16LE(machine, 18);
  return buffer;
}

function machO(cpuType) {
  const buffer = Buffer.alloc(64);
  buffer.writeUInt32LE(0xfeedfacf, 0);
  buffer.writeUInt32LE(cpuType, 4);
  return buffer;
}

function pe(machine) {
  const buffer = Buffer.alloc(256);
  buffer.writeUInt16LE(0x5a4d, 0);
  buffer.writeUInt32LE(0x80, 0x3c);
  buffer.writeUInt32LE(0x00004550, 0x80);
  buffer.writeUInt16LE(machine, 0x84);
  return buffer;
}

const FIXTURES = {
  "linux-x64": elf(0x3e),
  "linux-arm64": elf(0xb7),
  "darwin-x64": machO(0x01000007),
  "darwin-arm64": machO(0x0100000c),
  "win32-x64": pe(0x8664)
};

async function writeFixture(t, content) {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "agent-dump-validate-"));
  t.after(() => fs.rm(dir, { recursive: true, force: true }));
  const filePath = path.join(dir, "agent-dump");
  await fs.writeFile(filePath, content);
  return filePath;
}

test("identifies each real binary format and architecture", async (t) => {
  for (const [label, content] of Object.entries(FIXTURES)) {
    const filePath = await writeFixture(t, content);
    const identified = await identifyBinary(filePath);
    const [platform, arch] = label.split("-");
    assert.equal(identified.arch, arch, label);
    assert.equal(
      identified.format,
      { linux: "ELF", darwin: "Mach-O", win32: "PE" }[platform],
      label
    );
  }
});

test("accepts a correctly staged binary for every target", async (t) => {
  for (const target of STAGED_TARGETS) {
    const filePath = await writeFixture(t, FIXTURES[target]);
    await validateStagedBinary(target, filePath);
  }
});

test("rejects two swapped darwin binaries", async (t) => {
  const armAsIntel = await writeFixture(t, FIXTURES["darwin-arm64"]);
  await assert.rejects(
    validateStagedBinary("darwin-x64", armAsIntel),
    /is Mach-O\/arm64, expected Mach-O\/x64/
  );

  const intelAsArm = await writeFixture(t, FIXTURES["darwin-x64"]);
  await assert.rejects(
    validateStagedBinary("darwin-arm64", intelAsArm),
    /is Mach-O\/x64, expected Mach-O\/arm64/
  );
});

test("rejects a linux binary staged as the windows package", async (t) => {
  const filePath = await writeFixture(t, FIXTURES["linux-x64"]);
  await assert.rejects(validateStagedBinary("win32-x64", filePath), /is ELF\/x64, expected PE\/x64/);
});

test("rejects a wrong architecture for the same format", async (t) => {
  const filePath = await writeFixture(t, FIXTURES["linux-arm64"]);
  await assert.rejects(validateStagedBinary("linux-x64", filePath), /is ELF\/arm64, expected ELF\/x64/);
});

test("rejects an empty file", async (t) => {
  const filePath = await writeFixture(t, Buffer.alloc(0));
  await assert.rejects(validateStagedBinary("linux-x64", filePath), /is empty/);
});

test("rejects a shell script that is not a native executable", async (t) => {
  const filePath = await writeFixture(t, Buffer.from("#!/bin/sh\necho hi\n", "utf8"));
  await assert.rejects(validateStagedBinary("linux-x64", filePath), /is unknown\/unknown/);
});

test("rejects a target with no declared expectation", async (t) => {
  const filePath = await writeFixture(t, FIXTURES["linux-x64"]);
  await assert.rejects(validateStagedBinary("linux-riscv64", filePath), /No expected binary format declared/);
});
