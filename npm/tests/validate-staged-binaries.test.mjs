import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import { NATIVE_TARGETS } from "../scripts/native-targets.mjs";
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

function executableFixture(format, arch) {
  const machine = {
    ELF: { x64: 0x3e, arm64: 0xb7 },
    "Mach-O": { x64: 0x01000007, arm64: 0x0100000c },
    PE: { x64: 0x8664, arm64: 0xaa64 }
  }[format]?.[arch];
  if (machine === undefined) {
    throw new Error(`No fixture for ${format}/${arch}`);
  }
  return { ELF: elf, "Mach-O": machO, PE: pe }[format](machine);
}

async function writeFixture(t, content) {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "agent-dump-validate-"));
  t.after(() => fs.rm(dir, { recursive: true, force: true }));
  const filePath = path.join(dir, "agent-dump");
  await fs.writeFile(filePath, content);
  return filePath;
}

test("identifies each real binary format and architecture", async (t) => {
  for (const target of NATIVE_TARGETS) {
    const filePath = await writeFixture(t, executableFixture(target.binaryFormat, target.arch));
    const identified = await identifyBinary(filePath);
    assert.equal(identified.arch, target.arch, target.target);
    assert.equal(identified.format, target.binaryFormat, target.target);
  }
});

test("accepts a correctly staged binary for every target", async (t) => {
  assert.deepEqual(STAGED_TARGETS, NATIVE_TARGETS.map((target) => target.target));
  for (const target of NATIVE_TARGETS) {
    const filePath = await writeFixture(t, executableFixture(target.binaryFormat, target.arch));
    await validateStagedBinary(target.target, filePath);
  }
});

test("rejects two swapped darwin binaries", async (t) => {
  const armAsIntel = await writeFixture(t, executableFixture("Mach-O", "arm64"));
  await assert.rejects(
    validateStagedBinary("darwin-x64", armAsIntel),
    /is Mach-O\/arm64, expected Mach-O\/x64/
  );

  const intelAsArm = await writeFixture(t, executableFixture("Mach-O", "x64"));
  await assert.rejects(
    validateStagedBinary("darwin-arm64", intelAsArm),
    /is Mach-O\/x64, expected Mach-O\/arm64/
  );
});

test("rejects a linux binary staged as the windows package", async (t) => {
  const filePath = await writeFixture(t, executableFixture("ELF", "x64"));
  await assert.rejects(validateStagedBinary("win32-x64", filePath), /is ELF\/x64, expected PE\/x64/);
});

test("rejects a wrong architecture for the same format", async (t) => {
  const filePath = await writeFixture(t, executableFixture("ELF", "arm64"));
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
  const filePath = await writeFixture(t, executableFixture("ELF", "x64"));
  await assert.rejects(validateStagedBinary("linux-riscv64", filePath), /Unsupported native target/);
});
