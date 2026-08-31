import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";

import { NATIVE_TARGETS } from "../scripts/native-targets.mjs";
import { main, PublishOutcome, publishPackageIfNeeded, releaseTarballPaths } from "../scripts/publish-if-needed.mjs";

const localIntegrity = "sha512-local";
const localMetadata = JSON.stringify([
  { name: "@agent-dump/cli-test", version: "1.2.3", integrity: localIntegrity }
]);
const missing = JSON.stringify({ error: { code: "E404" } });

function command(status, stdout = "", stderr = "") {
  return { status, stdout, stderr };
}

function queuedRunner(responses, calls) {
  return (args) => {
    calls.push(args);
    const response = responses.shift();
    assert.ok(response, `unexpected npm command: ${args.join(" ")}`);
    return response;
  };
}

test("publishes a package version that is absent and verifies its download", async () => {
  const calls = [];
  const run = queuedRunner(
    [command(0, localMetadata), command(1, missing), command(0), command(0, localMetadata)],
    calls
  );

  const outcome = await publishPackageIfNeeded("./package", { run, log() {} });

  assert.equal(outcome, PublishOutcome.PUBLISHED);
  assert.deepEqual(calls[2], ["publish", "./package", "--provenance", "--access", "public"]);
  assert.deepEqual(calls[3], [
    "pack", "@agent-dump/cli-test@1.2.3", "--json", "--dry-run", "--ignore-scripts", "--prefer-online",
    "--fetch-retries=0", "--fetch-timeout=15000"
  ]);
});

test("skips an identical package version but still verifies its download", async () => {
  const calls = [];
  const run = queuedRunner(
    [command(0, localMetadata), command(0, JSON.stringify(localIntegrity)), command(0, localMetadata)],
    calls
  );

  const outcome = await publishPackageIfNeeded("./package", { run, log() {} });

  assert.equal(outcome, PublishOutcome.SKIPPED);
  assert.equal(calls.length, 3);
});

test("rejects an existing version with different contents", async () => {
  const calls = [];
  const run = queuedRunner([command(0, localMetadata), command(0, JSON.stringify("sha512-other"))], calls);

  await assert.rejects(
    () => publishPackageIfNeeded("./package", { run, log() {} }),
    /already exists with different contents/
  );
  assert.equal(calls.length, 2);
});

test("recovers when an identical concurrent publish wins the race", async () => {
  const calls = [];
  const run = queuedRunner(
    [
      command(0, localMetadata),
      command(1, missing),
      command(1, "", "publish conflict"),
      command(0, JSON.stringify(localIntegrity)),
      command(0, localMetadata)
    ],
    calls
  );

  const outcome = await publishPackageIfNeeded("./package", { run, log() {} });

  assert.equal(outcome, PublishOutcome.RECOVERED);
  assert.equal(calls.length, 5);
});

test("does not treat registry failures as a missing package", async () => {
  const calls = [];
  const run = queuedRunner([command(0, localMetadata), command(1, "", "network unavailable")], calls);

  await assert.rejects(() => publishPackageIfNeeded("./package", { run, log() {} }), /network unavailable/);
  assert.equal(calls.length, 2);
});

test("waits for a processed native package before publishing the wrapper", async () => {
  const calls = [];
  const waits = [];
  const logs = [];
  const wrapperMetadata = localMetadata.replace("cli-test", "cli");
  const run = queuedRunner([
    command(0, localMetadata), command(1, missing), command(0),
    command(1, JSON.stringify({ error: { code: "ETARGET" } })),
    command(1, missing), command(0, localMetadata),
    command(0, wrapperMetadata), command(1, missing), command(0), command(0, wrapperMetadata)
  ], calls);

  await main(["./native", "./wrapper"], {
    run,
    log: (message) => logs.push(message),
    wait: async (delay) => { waits.push(delay); }
  });

  assert.deepEqual(waits, [15_000, 15_000]);
  assert.deepEqual(calls.filter(([verb]) => verb === "publish").map(([, file]) => file), ["./native", "./wrapper"]);
  assert.equal(calls[5][1], "@agent-dump/cli-test@1.2.3");
  assert.equal(calls[6][1], "./wrapper");
  assert.ok(logs.some((message) => message.includes("ETARGET")));
  assert.ok(logs.some((message) => message.includes("E404")));
});

test("stops the release if a published package never becomes downloadable", async () => {
  const calls = [];
  const waits = [];
  const run = queuedRunner([
    command(0, localMetadata), command(1, missing), command(0),
    ...Array.from({ length: 40 }, () => command(1, missing, "version still processing"))
  ], calls);

  await assert.rejects(() => main(["./native", "./wrapper"], {
    run,
    log() {},
    wait: async (delay) => { waits.push(delay); }
  }), /@agent-dump\/cli-test@1\.2\.3 is still unavailable after 40 checks:\n.*version still processing/s);

  assert.equal(waits.length, 39);
  assert.ok(!calls.some(([, file]) => file === "./wrapper"));
  assert.equal(calls.filter(([verb]) => verb === "publish").length, 1);
});

for (const failure of [
  command(1, JSON.stringify({ error: { code: "E403" } }), "access denied"),
  command(1, "", "network unavailable"),
  { ...command(null), error: new Error("npm not found") }
]) {
  test(`fails immediately on a download check error: ${failure.stderr || failure.error.message}`, async () => {
    const calls = [];
    const run = queuedRunner([
      command(0, localMetadata), command(1, missing), command(0), failure
    ], calls);

    await assert.rejects(() => publishPackageIfNeeded("./package", {
      run, log() {}, wait: async () => assert.fail("must not retry this failure")
    }), /Could not check download availability/);
    assert.equal(calls.length, 4);
  });
}

for (const metadata of [
  localMetadata.replace(localIntegrity, "sha512-other"),
  localMetadata.replace("1.2.3", "1.2.4"),
  localMetadata.replace("cli-test", "cli-other"),
  "[]",
  "invalid JSON"
]) {
  test(`rejects downloaded metadata that does not match the release: ${metadata}`, async () => {
    const calls = [];
    const run = queuedRunner([
      command(0, localMetadata), command(1, missing), command(0), command(0, metadata)
    ], calls);

    await assert.rejects(() => publishPackageIfNeeded("./package", {
      run, log() {}, wait: async () => assert.fail("must not retry invalid metadata")
    }), /does not match the release tarball|npm returned invalid JSON/);
    assert.equal(calls.length, 4);
  });
}

test("release tarball list contains every platform before the wrapper", () => {
  const tarballs = releaseTarballPaths("/tmp/agent-dump-packed");

  assert.equal(tarballs.length, NATIVE_TARGETS.length + 1);
  assert.deepEqual(
    tarballs.slice(0, -1).map((tarball) => path.basename(tarball).replace(/-\d+\.\d+\.\d+\.tgz$/, "")),
    NATIVE_TARGETS.map((target) => target.packageName.slice(1).replace("/", "-"))
  );
  assert.match(path.basename(tarballs.at(-1)), /^agent-dump-cli-\d+\.\d+\.\d+\.tgz$/);
});
