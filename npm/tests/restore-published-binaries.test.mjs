import assert from "node:assert/strict";
import { writeFileSync } from "node:fs";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { gzipSync } from "node:zlib";

import { RestoreOutcome, restorePublishedBinary } from "../scripts/restore-published-binaries.mjs";

async function tempRoot(t, prefix) {
  const root = await mkdtemp(path.join(os.tmpdir(), prefix));
  await mkdir(path.join(root, "bin"), { recursive: true });
  t.after(() => rm(root, { recursive: true, force: true }));
  return root;
}

function tarEntry(name, content) {
  const header = Buffer.alloc(512);
  header.write(name, 0, 100, "utf8");
  header.write("0000755\0", 100, 8, "ascii");
  header.write("0000000\0", 108, 8, "ascii");
  header.write("0000000\0", 116, 8, "ascii");
  header.write(content.length.toString(8).padStart(11, "0") + "\0", 124, 12, "ascii");
  header.write("00000000000\0", 136, 12, "ascii");
  header.fill(" ", 148, 156);
  header.write("0", 156, 1, "ascii");
  header.write("ustar\0", 257, 6, "ascii");
  header.write("00", 263, 2, "ascii");
  let checksum = 0;
  for (const byte of header) checksum += byte;
  header.write(checksum.toString(8).padStart(6, "0") + "\0 ", 148, 8, "ascii");
  const padding = Buffer.alloc((512 - (content.length % 512)) % 512);
  return Buffer.concat([header, content, padding]);
}

function packageTarball(executableName, binary) {
  return gzipSync(Buffer.concat([tarEntry(`package/bin/${executableName}`, binary), Buffer.alloc(1024)]));
}

function command(status, stdout = "", stderr = "") {
  return { status, stdout, stderr };
}

function localMetadata(integrity) {
  return JSON.stringify([{ name: "@agent-dump/cli-test", version: "1.2.3", integrity }]);
}

test("leaves a newly staged binary when the version is unpublished", async (t) => {
  const packageRoot = await tempRoot(t, "agent-dump-restore-unpublished-");
  const binaryPath = path.join(packageRoot, "bin", "agent-dump");
  await writeFile(binaryPath, "local");
  const responses = [command(0, localMetadata("sha512-local")), command(1, JSON.stringify({ error: { code: "E404" } }))];

  const outcome = restorePublishedBinary(packageRoot, "agent-dump", {
    run: () => responses.shift(),
    log() {}
  });

  assert.equal(outcome, RestoreOutcome.UNPUBLISHED);
  assert.equal(await readFile(binaryPath, "utf8"), "local");
});

test("restores the exact binary from an existing immutable package", async (t) => {
  const packageRoot = await tempRoot(t, "agent-dump-restore-published-");
  const binaryPath = path.join(packageRoot, "bin", "agent-dump");
  await writeFile(binaryPath, "new-build");
  const publishedBinary = Buffer.from("published-build");
  const remoteIntegrity = "sha512-remote";
  let localPackCount = 0;

  const run = (args) => {
    if (args[0] === "view") {
      return command(0, JSON.stringify(remoteIntegrity));
    }
    if (args[0] === "pack" && args.includes("--pack-destination")) {
      const destination = args[args.indexOf("--pack-destination") + 1];
      const filename = "agent-dump-cli-test-1.2.3.tgz";
      writeFileSync(path.join(destination, filename), packageTarball("agent-dump", publishedBinary));
      return command(0, JSON.stringify([{ filename, integrity: remoteIntegrity }]));
    }
    localPackCount += 1;
    return command(0, localMetadata(localPackCount === 1 ? "sha512-local" : remoteIntegrity));
  };

  const outcome = restorePublishedBinary(packageRoot, "agent-dump", { run, log() {} });

  assert.equal(outcome, RestoreOutcome.RESTORED);
  assert.deepEqual(await readFile(binaryPath), publishedBinary);
});

test("fails if the current manifest cannot reproduce the published tarball", async (t) => {
  const packageRoot = await tempRoot(t, "agent-dump-restore-conflict-");
  await writeFile(path.join(packageRoot, "bin", "agent-dump"), "new-build");
  const remoteIntegrity = "sha512-remote";
  let localPackCount = 0;

  const run = (args) => {
    if (args[0] === "view") {
      return command(0, JSON.stringify(remoteIntegrity));
    }
    if (args[0] === "pack" && args.includes("--pack-destination")) {
      const destination = args[args.indexOf("--pack-destination") + 1];
      const filename = "agent-dump-cli-test-1.2.3.tgz";
      writeFileSync(path.join(destination, filename), packageTarball("agent-dump", Buffer.from("published")));
      return command(0, JSON.stringify([{ filename, integrity: remoteIntegrity }]));
    }
    localPackCount += 1;
    return command(0, localMetadata(localPackCount === 1 ? "sha512-local" : "sha512-still-different"));
  };

  assert.throws(
    () => restorePublishedBinary(packageRoot, "agent-dump", { run, log() {} }),
    /cannot be reconstructed/
  );
});
