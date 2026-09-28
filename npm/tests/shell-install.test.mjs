import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { execFileSync, spawnSync } from "node:child_process";
import {
  chmodSync,
  mkdtempSync,
  mkdirSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { NATIVE_TARGETS } from "../scripts/native-targets.mjs";

const unixTest = process.platform === "win32" ? test.skip : test;

const installer = fileURLToPath(new URL("../../scripts/install.sh", import.meta.url));

function fixture(t) {
  const root = mkdtempSync(join(tmpdir(), "agent-dump install 测试 "));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const bin = join(root, "bin");
  const assets = join(root, "assets");
  const destination = join(root, "install", "agent-dump");
  mkdirSync(bin);
  mkdirSync(assets);
  const executable = (name, content) => {
    writeFileSync(name, content);
    chmodSync(name, 0o755);
  };
  executable(
    join(bin, "uname"),
    '#!/bin/sh\ncase "$1" in -s) echo Darwin;; -m) echo arm64;; esac\n',
  );
  executable(
    join(bin, "curl"),
    `#!/bin/sh
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o) shift; output=$1 ;;
    https://*) url=$1 ;;
  esac
  shift
done
case "$url" in
  */latest) printf 'https://github.com/xingkaixin/agent-dump/releases/tag/v1.0.0';;
  *) cp "$TEST_ASSETS/$(basename "$url")" "$output";;
esac
`,
  );
  executable(join(assets, "agent-dump"), '#!/bin/sh\necho "agent-dump 1.0.0"\n');
  const name = "agent-dump-darwin-arm64";
  writeFileSync(join(assets, name), readFileSync(join(assets, "agent-dump")));
  const hash = createHash("sha256")
    .update(readFileSync(join(assets, name)))
    .digest("hex");
  writeFileSync(join(assets, "SHA256SUMS"), `${hash}  ${name}\n`);
  const run = (env = {}) =>
    spawnSync("sh", [installer], {
      encoding: "utf8",
      env: {
        ...process.env,
        AGENT_DUMP_VERSION: "",
        AGENT_DUMP_INSTALL_DIR: join(root, "install"),
        PATH: `${bin}:${process.env.PATH}`,
        TEST_ASSETS: assets,
        ...env,
      },
    });
  return { root, bin, assets, destination, run, executable };
}

unixTest("installs latest into a path with spaces and leaves a current installation intact", (t) => {
  const f = fixture(t);
  let result = f.run();
  assert.equal(result.status, 0, result.stderr);
  assert.equal(
    execFileSync(f.destination, ["--version"], { encoding: "utf8" }).trim(),
    "agent-dump 1.0.0",
  );
  rmSync(join(f.assets, "SHA256SUMS"));
  result = f.run({ AGENT_DUMP_VERSION: "v1.0.0" });
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /already installed/);
});

unixTest("failed download and checksum mismatch preserve the old executable", (t) => {
  const f = fixture(t);
  mkdirSync(join(f.root, "install"));
  const old = '#!/bin/sh\necho "agent-dump 0.9.0"\n';
  f.executable(f.destination, old);
  writeFileSync(
    join(f.assets, "SHA256SUMS"),
    `${"0".repeat(64)}  agent-dump-darwin-arm64\n`,
  );
  assert.notEqual(f.run().status, 0);
  assert.equal(readFileSync(f.destination, "utf8"), old);
  rmSync(join(f.assets, "SHA256SUMS"));
  assert.notEqual(f.run().status, 0);
  assert.equal(readFileSync(f.destination, "utf8"), old);
});

unixTest("updates an older executable only after successful verification", (t) => {
  const f = fixture(t);
  mkdirSync(join(f.root, "install"));
  f.executable(f.destination, '#!/bin/sh\necho "agent-dump 0.9.0"\n');
  const result = f.run({ AGENT_DUMP_VERSION: "1.0.0" });
  assert.equal(result.status, 0, result.stderr);
  assert.match(readFileSync(f.destination, "utf8"), /1\.0\.0/);
});

unixTest("a checksummed executable that cannot run does not replace the old version", (t) => {
  const f = fixture(t);
  mkdirSync(join(f.root, "install"));
  const old = '#!/bin/sh\necho "agent-dump 0.9.0"\n';
  f.executable(f.destination, old);
  f.executable(join(f.assets, "agent-dump"), "#!/bin/sh\nexit 1\n");
  const name = "agent-dump-darwin-arm64";
  writeFileSync(join(f.assets, name), readFileSync(join(f.assets, "agent-dump")));
  const hash = createHash("sha256")
    .update(readFileSync(join(f.assets, name)))
    .digest("hex");
  writeFileSync(join(f.assets, "SHA256SUMS"), `${hash}  ${name}\n`);
  assert.notEqual(f.run().status, 0);
  assert.equal(readFileSync(f.destination, "utf8"), old);
});

unixTest("refuses package-manager symlinks and unsupported platforms", (t) => {
  const f = fixture(t);
  mkdirSync(join(f.root, "install"));
  symlinkSync(join(f.assets, "agent-dump"), f.destination);
  assert.match(f.run().stderr, /Refusing to replace a symlink/);
  f.executable(join(f.bin, "uname"), "#!/bin/sh\necho unsupported\n");
  assert.match(f.run().stderr, /Supported platforms/);
});

unixTest("rejects old glibc before downloading", (t) => {
  const f = fixture(t);
  f.executable(
    join(f.bin, "uname"),
    '#!/bin/sh\ncase "$1" in -s) echo Linux;; -m) echo x86_64;; esac\n',
  );
  f.executable(join(f.bin, "getconf"), '#!/bin/sh\necho "glibc 2.16"\n');
  const result = f.run();
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /glibc 2.17/);
});

for (const target of NATIVE_TARGETS.filter((target) => target.platform !== "win32")) {
  unixTest(`installs the manifest's ${target.target} asset`, (t) => {
    const f = fixture(t);
    const system = target.platform === "darwin" ? "Darwin" : "Linux";
    const arch = target.arch === "x64" ? "x86_64" : "arm64";
    f.executable(join(f.bin, "uname"), `#!/bin/sh\ncase "$1" in -s) echo ${system};; -m) echo ${arch};; esac\n`);
    f.executable(join(f.bin, "getconf"), '#!/bin/sh\necho "glibc 2.17"\n');
    const payload = readFileSync(join(f.assets, "agent-dump"));
    writeFileSync(join(f.assets, target.releaseAssetName), payload);
    const hash = createHash("sha256").update(payload).digest("hex");
    writeFileSync(join(f.assets, "SHA256SUMS"), `${hash}  ${target.releaseAssetName}\n`);
    const result = f.run();
    assert.equal(result.status, 0, result.stderr);
    assert.equal(readFileSync(f.destination, "utf8"), payload.toString());
  });
}
