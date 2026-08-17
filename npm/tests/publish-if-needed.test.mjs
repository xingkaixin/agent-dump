import assert from "node:assert/strict";
import test from "node:test";

import { PublishOutcome, publishPackageIfNeeded } from "../scripts/publish-if-needed.mjs";

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

test("publishes a package version that is absent", () => {
  const calls = [];
  const run = queuedRunner([command(0, localMetadata), command(1, missing), command(0)], calls);

  const outcome = publishPackageIfNeeded("./package", { run, log() {} });

  assert.equal(outcome, PublishOutcome.PUBLISHED);
  assert.deepEqual(calls[2], ["publish", "./package", "--provenance", "--access", "public"]);
});

test("skips an identical package version", () => {
  const calls = [];
  const run = queuedRunner([command(0, localMetadata), command(0, JSON.stringify(localIntegrity))], calls);

  const outcome = publishPackageIfNeeded("./package", { run, log() {} });

  assert.equal(outcome, PublishOutcome.SKIPPED);
  assert.equal(calls.length, 2);
});

test("rejects an existing version with different contents", () => {
  const calls = [];
  const run = queuedRunner([command(0, localMetadata), command(0, JSON.stringify("sha512-other"))], calls);

  assert.throws(
    () => publishPackageIfNeeded("./package", { run, log() {} }),
    /already exists with different contents/
  );
  assert.equal(calls.length, 2);
});

test("recovers when an identical concurrent publish wins the race", () => {
  const calls = [];
  const run = queuedRunner(
    [
      command(0, localMetadata),
      command(1, missing),
      command(1, "", "publish conflict"),
      command(0, JSON.stringify(localIntegrity))
    ],
    calls
  );

  const outcome = publishPackageIfNeeded("./package", { run, log() {} });

  assert.equal(outcome, PublishOutcome.RECOVERED);
  assert.equal(calls.length, 4);
});

test("does not treat registry failures as a missing package", () => {
  const calls = [];
  const run = queuedRunner([command(0, localMetadata), command(1, "", "network unavailable")], calls);

  assert.throws(() => publishPackageIfNeeded("./package", { run, log() {} }), /network unavailable/);
  assert.equal(calls.length, 2);
});
