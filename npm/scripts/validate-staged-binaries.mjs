import { open, stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { NATIVE_TARGETS, getNativeTarget } from "./native-targets.mjs";

// 每个 target 的期望格式与 CPU 架构。只检查「非空」或 `file` 输出里没有 "text"
// 挡不住最可能出的那类错：把两个 darwin binary 放反，或把 linux binary staged 到
// win32 包——两者都是合法的原生可执行文件，却在用户机器上根本跑不起来。而且
// `file` 在 Windows runner 上不存在，那条分支此前等于完全不检查。
// Mach-O cputype：CPU_ARCH_ABI64 (0x01000000) | CPU_TYPE_X86 (7) / CPU_TYPE_ARM (12)
const MACHO_CPU_TYPES = new Map([
  [0x01000007, "x64"],
  [0x0100000c, "arm64"]
]);
// ELF e_machine
const ELF_MACHINES = new Map([
  [0x3e, "x64"],
  [0xb7, "arm64"]
]);
// PE IMAGE_FILE_MACHINE
const PE_MACHINES = new Map([
  [0x8664, "x64"],
  [0xaa64, "arm64"]
]);

function describe(map, value) {
  return map.get(value) ?? `unknown(0x${value.toString(16)})`;
}

async function readHead(binaryPath, length) {
  const handle = await open(binaryPath, "r");
  try {
    const buffer = Buffer.alloc(length);
    const { bytesRead } = await handle.read(buffer, 0, length, 0);
    return buffer.subarray(0, bytesRead);
  } finally {
    await handle.close();
  }
}

export async function identifyBinary(binaryPath) {
  // PE 的 Machine 字段位置由 0x3C 处的偏移决定，读 1 KiB 足以覆盖常见布局
  const head = await readHead(binaryPath, 1024);

  if (head.length >= 20 && head.readUInt32BE(0) === 0x7f454c46) {
    return { format: "ELF", arch: describe(ELF_MACHINES, head.readUInt16LE(18)) };
  }

  if (head.length >= 8) {
    const magic = head.readUInt32LE(0);
    // MH_MAGIC_64 / MH_CIGAM_64；32 位 Mach-O 和 fat binary 都不是本项目的产物
    if (magic === 0xfeedfacf || magic === 0xcffaedfe) {
      const cpuType = magic === 0xfeedfacf ? head.readUInt32LE(4) : head.readUInt32BE(4);
      return { format: "Mach-O", arch: describe(MACHO_CPU_TYPES, cpuType) };
    }
  }

  if (head.length >= 0x40 && head.readUInt16LE(0) === 0x5a4d) {
    const peOffset = head.readUInt32LE(0x3c);
    if (peOffset + 6 <= head.length && head.readUInt32LE(peOffset) === 0x00004550) {
      return { format: "PE", arch: describe(PE_MACHINES, head.readUInt16LE(peOffset + 4)) };
    }
    return { format: "PE", arch: "unknown" };
  }

  return { format: "unknown", arch: "unknown" };
}

export function stagedBinaryPath(target) {
  return getNativeTarget(target).binaryPath;
}

export async function validateStagedBinary(target, binaryPath = stagedBinaryPath(target)) {
  const expected = getNativeTarget(target);

  const binaryStat = await stat(binaryPath);
  if (binaryStat.size <= 0) {
    throw new Error(`Staged binary for ${target} is empty: ${binaryPath}`);
  }

  const actual = await identifyBinary(binaryPath);
  if (actual.format !== expected.binaryFormat || actual.arch !== expected.arch) {
    throw new Error(
      `Staged binary for ${target} is ${actual.format}/${actual.arch}, ` +
        `expected ${expected.binaryFormat}/${expected.arch}: ${binaryPath}`
    );
  }

  return actual;
}

export const STAGED_TARGETS = NATIVE_TARGETS.map((target) => target.target);

async function main() {
  for (const target of STAGED_TARGETS) {
    const actual = await validateStagedBinary(target);
    console.log(`  ${target}: ${actual.format}/${actual.arch}`);
  }
  console.log(`Validated staged binaries for ${STAGED_TARGETS.join(", ")}`);
}

if (import.meta.url === `file://${process.argv[1]}`) {
  await main();
}
