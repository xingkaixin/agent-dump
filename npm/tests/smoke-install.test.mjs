import assert from "node:assert/strict";
import test from "node:test";

import { validatePackedPlatformTarball } from "../scripts/smoke-install.mjs";

const version = "1.2.3";
const spec = {
  target: "linux-x64",
  packageName: "@agent-dump/cli-linux-x64",
  executableName: "agent-dump",
  platform: "linux",
  arch: "x64"
};

function validMetadata() {
  return {
    name: spec.packageName,
    version,
    files: [
      { path: "bin/agent-dump", size: 1024, mode: 0o755 },
      { path: "package.json", size: 400, mode: 0o644 }
    ]
  };
}

function validManifest() {
  return {
    name: spec.packageName,
    version,
    os: ["linux"],
    cpu: ["x64"]
  };
}

test("accepts a packed platform tarball with exact target metadata", () => {
  assert.doesNotThrow(() => validatePackedPlatformTarball(validMetadata(), validManifest(), spec, version));
});

test("rejects a packed platform tarball without its executable", () => {
  const metadata = validMetadata();
  metadata.files = metadata.files.filter((file) => !file.path.startsWith("bin/"));

  assert.throws(
    () => validatePackedPlatformTarball(metadata, validManifest(), spec, version),
    /must contain only bin\/agent-dump under bin\//
  );
});

test("rejects a packed platform tarball with the wrong executable", () => {
  const metadata = validMetadata();
  metadata.files[0].path = "bin/agent-dump.exe";

  assert.throws(
    () => validatePackedPlatformTarball(metadata, validManifest(), spec, version),
    /must contain only bin\/agent-dump under bin\//
  );
});

test("rejects mismatched platform metadata", () => {
  const manifest = validManifest();
  manifest.os = ["darwin"];

  assert.throws(
    () => validatePackedPlatformTarball(validMetadata(), manifest, spec, version),
    /does not declare linux\/x64/
  );
});

test("rejects a non-executable Unix binary", () => {
  const metadata = validMetadata();
  metadata.files[0].mode = 0o644;

  assert.throws(
    () => validatePackedPlatformTarball(metadata, validManifest(), spec, version),
    /executable is not executable/
  );
});
