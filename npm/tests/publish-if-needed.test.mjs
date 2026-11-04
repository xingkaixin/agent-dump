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

test("release tarball list contains every platform before the wrapper", () => {
  const tarballs = releaseTarballPaths("/tmp/agent-dump-packed");

  assert.equal(tarballs.length, NATIVE_TARGETS.length + 1);
  assert.deepEqual(
    tarballs.slice(0, -1).map((tarball) => path.basename(tarball).replace(/-\d+\.\d+\.\d+\.tgz$/, "")),
    NATIVE_TARGETS.map((target) => target.packageName.slice(1).replace("/", "-"))
  );
  assert.match(path.basename(tarballs.at(-1)), /^agent-dump-cli-\d+\.\d+\.\d+\.tgz$/);
});
