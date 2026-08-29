import test from "node:test";
import assert from "node:assert/strict";
import crypto from "node:crypto";
import { createRequire } from "node:module";
import fs from "node:fs/promises";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import zlib from "node:zlib";

const require = createRequire(import.meta.url);
const {
  DEFAULT_TOTAL_TIMEOUT_MS,
  MAX_COMPRESSED_TARBALL_BYTES,
  MAX_DECOMPRESSED_TAR_BYTES,
  MAX_NPM_OUTPUT_BYTES,
  downloadPackageTarball,
  ensureBinary,
  extractBinaryFromTarball,
  getNpmInvocation,
  getVendorBinaryPath,
  installBinary,
  publishBinaryAtomically,
  runNpm,
  sha256
} = require("../packages/cli/lib/install-binary.cjs");
const { getBinarySpec } = require("../packages/cli/lib/targets.cjs");

// 每个临时根都在创建时就注册清理：node:test 的 t.after() 在成功、assert 失败与
// Promise reject 后都会执行，靠 finally 要在九处各写一遍，靠进程退出则什么都不清。
async function tempRoot(t, prefix) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), prefix));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  return root;
}

function createTarEntry(name, content) {
  const header = Buffer.alloc(512, 0);
  header.write(name);
  header.write("0000777\0", 100);
  header.write("0000000\0", 108);
  header.write("0000000\0", 116);
  header.write(content.length.toString(8).padStart(11, "0") + "\0", 124);
  header.write("00000000000\0", 136);
  header.write("        ", 148);
  header.write("0", 156);
  header.write("ustar\0", 257);
  header.write("00", 263);

  let checksum = 0;
  for (const byte of header) {
    checksum += byte;
  }
  header.write(checksum.toString(8).padStart(6, "0") + "\0 ", 148);

  const paddingSize = (512 - (content.length % 512)) % 512;
  return Buffer.concat([header, content, Buffer.alloc(paddingSize, 0)]);
}

function createTarGz(entries) {
  const tarBody = Buffer.concat([
    ...entries.map(({ name, content }) => createTarEntry(name, content)),
    Buffer.alloc(1024, 0)
  ]);
  return zlib.gzipSync(tarBody);
}

test("extractBinaryFromTarball reads the packaged executable from the tarball", () => {
  const spec = getBinarySpec("win32", "x64");
  const binary = Buffer.from("fake-exe");
  const tarball = createTarGz([
    { name: "package/package.json", content: Buffer.from('{"name":"@agent-dump/cli-win32-x64"}') },
    { name: "package/bin/agent-dump.exe", content: binary }
  ]);

  assert.deepEqual(extractBinaryFromTarball(tarball, spec), binary);
});

test("installBinary verifies and writes a supplied platform tarball", async (t) => {
  const packageRoot = await tempRoot(t, "agent-dump-install-");
  const version = "0.6.13";
  const spec = getBinarySpec("linux", "x64");
  const binary = Buffer.from("#!/usr/bin/env bash\necho help\n", "utf8");
  const tarball = createTarGz([
    { name: "package/package.json", content: Buffer.from('{"name":"@agent-dump/cli-linux-x64"}') },
    { name: "package/bin/agent-dump", content: binary }
  ]);
  const tarballPath = path.join(packageRoot, "platform.tgz");
  await fs.writeFile(tarballPath, tarball);

  const vendorPath = await installBinary({
    packageRoot,
    version,
    platform: "linux",
    arch: "x64",
    checksums: {
      [version]: {
        [spec.target]: sha256(binary)
      }
    },
    tarballPath
  });

  assert.equal(vendorPath, getVendorBinaryPath(packageRoot, spec));
  assert.deepEqual(await fs.readFile(vendorPath), binary);
});

test("installBinary honors scoped registry authentication from npm config", async (t) => {
  const packageRoot = await tempRoot(t, "agent-dump-private-registry-");
  const version = "0.6.13";
  const spec = getBinarySpec("linux", "x64");
  const binary = Buffer.from("private-registry-binary");
  const tarball = createTarGz([
    {
      name: "package/package.json",
      content: Buffer.from(JSON.stringify({ name: spec.packageName, version }))
    },
    { name: "package/bin/agent-dump", content: binary }
  ]);
  const integrity = `sha512-${crypto.createHash("sha512").update(tarball).digest("base64")}`;
  const requests = [];

  await withServer(
    (req, res) => {
      const authorization = req.headers.authorization ?? "<missing>";
      requests.push({ url: req.url, authorization });

      if (!req.url.startsWith("/scoped/") || authorization !== "Bearer test-token") {
        res.writeHead(401, { "content-type": "application/json" });
        res.end(JSON.stringify({ error: "authentication required" }));
        return;
      }
      if (req.url.endsWith(".tgz")) {
        res.writeHead(200, { "content-type": "application/octet-stream" });
        res.end(tarball);
        return;
      }

      const origin = `http://${req.headers.host}`;
      res.writeHead(200, { "content-type": "application/json" });
      res.end(
        JSON.stringify({
          name: spec.packageName,
          versions: {
            [version]: {
              name: spec.packageName,
              version,
              dist: {
                integrity,
                tarball: `${origin}/scoped/tarballs/cli-linux-x64-${version}.tgz`
              }
            }
          }
        })
      );
    },
    async (url) => {
      const origin = new URL(url).origin;
      const npmrcPath = path.join(packageRoot, ".npmrc");
      const userconfigPath = path.join(packageRoot, "empty-user.npmrc");
      const cachePath = path.join(packageRoot, "npm-cache");
      await fs.writeFile(
        npmrcPath,
        [
          `registry=${origin}/default/`,
          `@agent-dump:registry=${origin}/scoped/`,
          `//${new URL(origin).host}/scoped/:_authToken=test-token`
        ].join("\n")
      );
      await fs.writeFile(userconfigPath, "");

      const vendorPath = await installBinary({
        packageRoot,
        version,
        platform: "linux",
        arch: "x64",
        checksums: { [version]: { [spec.target]: sha256(binary) } },
        env: {
          ...process.env,
          INIT_CWD: packageRoot,
          npm_config_cache: cachePath,
          npm_config_local_prefix: packageRoot,
          npm_config_registry: `${origin}/default/`,
          npm_config_userconfig: userconfigPath
        }
      });

      assert.deepEqual(await fs.readFile(vendorPath), binary);
    }
  );

  assert.ok(requests.length >= 2);
  assert.ok(requests.every((request) => request.url.startsWith("/scoped/")));
  assert.ok(requests.every((request) => request.authorization === "Bearer test-token"));
});

test("installBinary fails on checksum mismatch", async (t) => {
  const packageRoot = await tempRoot(t, "agent-dump-install-mismatch-");
  const version = "0.6.13";
  const spec = getBinarySpec("win32", "x64");
  const tarball = createTarGz([
    { name: "package/package.json", content: Buffer.from('{"name":"@agent-dump/cli-win32-x64"}') },
    { name: "package/bin/agent-dump.exe", content: Buffer.from("bad-binary") }
  ]);
  const tarballPath = path.join(packageRoot, "platform.tgz");
  await fs.writeFile(tarballPath, tarball);

  await assert.rejects(
    installBinary({
      packageRoot,
      version,
      platform: "win32",
      arch: "x64",
      checksums: {
        [version]: {
          [spec.target]: "deadbeef"
        }
      },
      tarballPath
    }),
    /Checksum mismatch/
  );
});

test("ensureBinary returns an existing vendored binary that matches its checksum", async (t) => {
  const packageRoot = await tempRoot(t, "agent-dump-ensure-existing-");
  const spec = getBinarySpec("linux", "x64");
  const vendorPath = getVendorBinaryPath(packageRoot, spec);
  const version = "0.6.13";
  const existing = Buffer.from("existing-binary", "utf8");

  await fs.mkdir(path.dirname(vendorPath), { recursive: true });
  await fs.writeFile(vendorPath, existing);

  const ensuredPath = await ensureBinary({
    packageRoot,
    platform: "linux",
    arch: "x64",
    version,
    checksums: { [version]: { [spec.target]: sha256(existing) } },
    runNpmImpl: async () => {
      throw new Error("ensureBinary should not download when the installed binary is valid");
    }
  });

  assert.equal(ensuredPath, vendorPath);
  assert.deepEqual(await fs.readFile(vendorPath), existing);
});

test("ensureBinary installs the vendored binary when it is missing", async (t) => {
  const packageRoot = await tempRoot(t, "agent-dump-ensure-install-");
  const version = "0.6.13";
  const spec = getBinarySpec("linux", "x64");
  const binary = Buffer.from("#!/usr/bin/env bash\necho installed\n", "utf8");
  const tarball = createTarGz([
    { name: "package/package.json", content: Buffer.from('{"name":"@agent-dump/cli-linux-x64"}') },
    { name: "package/bin/agent-dump", content: binary }
  ]);
  const tarballPath = path.join(packageRoot, "platform.tgz");
  await fs.writeFile(tarballPath, tarball);

  const ensuredPath = await ensureBinary({
    packageRoot,
    version,
    platform: "linux",
    arch: "x64",
    checksums: {
      [version]: {
        [spec.target]: sha256(binary)
      }
    },
    tarballPath
  });

  assert.equal(ensuredPath, getVendorBinaryPath(packageRoot, spec));
  assert.deepEqual(await fs.readFile(ensuredPath), binary);
});

async function withServer(handler, run) {
  const server = http.createServer(handler);
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const url = `http://127.0.0.1:${server.address().port}/artifact`;
  try {
    return await run(url);
  } finally {
    server.close();
    server.closeAllConnections?.();
  }
}

test("downloadPackageTarball rejects an archive over the configured limit", async () => {
  const spec = getBinarySpec("linux", "x64");
  const version = "0.6.13";

  await assert.rejects(
    downloadPackageTarball(spec, version, {
      maxTarballBytes: 3,
      async runNpmImpl(_args, { env }) {
        const filename = "agent-dump-cli-linux-x64-0.6.13.tgz";
        await fs.writeFile(path.join(env.npm_config_pack_destination, filename), Buffer.alloc(4));
        return {
          stdout: JSON.stringify([
            { name: spec.packageName, version, filename, integrity: "sha512-test" }
          ]),
          stderr: ""
        };
      }
    }),
    /exceeds 3 bytes/
  );
});

test("downloadPackageTarball accepts npm scoped metadata filenames", async () => {
  const spec = getBinarySpec("linux", "x64");
  const version = "0.6.13";
  const tarball = Buffer.from("packed archive");

  const downloaded = await downloadPackageTarball(spec, version, {
    async runNpmImpl(_args, { env }) {
      const filename = "agent-dump-cli-linux-x64-0.6.13.tgz";
      await fs.writeFile(path.join(env.npm_config_pack_destination, filename), tarball);
      return {
        stdout: JSON.stringify([
          {
            name: spec.packageName,
            version,
            filename: `@agent-dump/cli-linux-x64-${version}.tgz`,
            integrity: "sha512-test"
          }
        ]),
        stderr: ""
      };
    }
  });

  assert.deepEqual(downloaded, tarball);
});

test("downloadPackageTarball rejects multiple npm tarballs", async () => {
  const spec = getBinarySpec("linux", "x64");
  const version = "0.6.13";

  await assert.rejects(
    downloadPackageTarball(spec, version, {
      async runNpmImpl(_args, { env }) {
        await Promise.all([
          fs.writeFile(path.join(env.npm_config_pack_destination, "first.tgz"), "first"),
          fs.writeFile(path.join(env.npm_config_pack_destination, "second.tgz"), "second")
        ]);
        return {
          stdout: JSON.stringify([
            {
              name: spec.packageName,
              version,
              filename: `@agent-dump/cli-linux-x64-${version}.tgz`,
              integrity: "sha512-test"
            }
          ]),
          stderr: ""
        };
      }
    }),
    /npm produced 2 package tarballs/
  );
});

test("downloadPackageTarball rejects a package version that is unsafe for the Windows shell", async () => {
  const spec = getBinarySpec("win32", "x64");

  await assert.rejects(
    downloadPackageTarball(spec, "0.6.13 & calc", {
      runNpmImpl: async () => assert.fail("invalid input must be rejected before npm starts")
    }),
    /Invalid package version/
  );
});

test("runNpm bounds subprocess output", async (t) => {
  const root = await tempRoot(t, "agent-dump-npm-output-");
  const npmExecPath = path.join(root, "npm-cli.js");
  await fs.writeFile(npmExecPath, 'process.stdout.write("x".repeat(1024));\n');

  await assert.rejects(
    runNpm(["pack"], {
      env: { ...process.env, npm_execpath: npmExecPath, npm_node_execpath: process.execPath },
      maxNpmOutputBytes: 32
    }),
    /npm output exceeded 32 bytes/
  );
});

test("runNpm terminates a subprocess after the total deadline", async (t) => {
  const root = await tempRoot(t, "agent-dump-npm-timeout-");
  const npmExecPath = path.join(root, "npm-cli.js");
  await fs.writeFile(npmExecPath, "setInterval(() => {}, 1000);\n");

  await assert.rejects(
    runNpm(["pack"], {
      env: { ...process.env, npm_execpath: npmExecPath, npm_node_execpath: process.execPath },
      npmTimeoutMs: 100
    }),
    /npm pack timed out after 100ms/
  );
});

test("getNpmInvocation uses cmd without enabling a child-process shell on Windows", () => {
  assert.deepEqual(getNpmInvocation({ ComSpec: "C:\\Windows\\System32\\cmd.exe" }, "win32"), {
    command: "C:\\Windows\\System32\\cmd.exe",
    prefixArgs: ["/d", "/s", "/c", "npm"],
    shell: false
  });
});

test("extractBinaryFromTarball rejects a small tarball that decompresses past the limit", () => {
  const bomb = zlib.gzipSync(Buffer.alloc(4 * 1024 * 1024));
  assert.ok(bomb.length < 64 * 1024, "the compressed input must stay small for this to be a real bomb");

  assert.throws(
    () => extractBinaryFromTarball(bomb, { packageName: "p", executableName: "e" }, { maxDecompressedBytes: 1024 }),
    /decompresses past the 1024 byte limit/
  );
});

test("production defaults keep every limit switched on", () => {
  assert.ok(MAX_COMPRESSED_TARBALL_BYTES > 0);
  assert.ok(MAX_DECOMPRESSED_TAR_BYTES > MAX_COMPRESSED_TARBALL_BYTES);
  assert.ok(MAX_NPM_OUTPUT_BYTES > 0);
  assert.ok(DEFAULT_TOTAL_TIMEOUT_MS > 0);
});

// AD-169：最终路径在任意时刻只能是旧的完整 binary 或新的完整 binary
async function buildInstallFixture(packageRoot, binary, version = "0.6.13") {
  const spec = getBinarySpec("linux", "x64");
  const tarball = createTarGz([
    { name: "package/package.json", content: Buffer.from('{"name":"@agent-dump/cli-linux-x64"}') },
    { name: "package/bin/agent-dump", content: binary }
  ]);
  const tarballPath = path.join(packageRoot, "platform.tgz");
  await fs.writeFile(tarballPath, tarball);

  return {
    spec,
    version,
    options: {
      platform: "linux",
      arch: "x64",
      version,
      checksums: { [version]: { [spec.target]: sha256(binary) } },
      tarballPath
    }
  };
}

async function listTempSiblings(vendorPath) {
  const entries = await fs.readdir(path.dirname(vendorPath));
  return entries.filter((name) => name.endsWith(".tmp"));
}

for (const [label, corrupt] of [
  ["a zero-byte file", Buffer.alloc(0)],
  ["a truncated file", Buffer.from("#!/usr/bin", "utf8")],
  ["a file with the wrong checksum", Buffer.from("something else entirely", "utf8")]
]) {
  test(`ensureBinary repairs ${label}`, async (t) => {
    const packageRoot = await tempRoot(t, "agent-dump-repair-");
    const binary = Buffer.from("#!/usr/bin/env bash\necho repaired\n", "utf8");
    const fixture = await buildInstallFixture(packageRoot, binary);
    const vendorPath = getVendorBinaryPath(packageRoot, fixture.spec);

    await fs.mkdir(path.dirname(vendorPath), { recursive: true });
    await fs.writeFile(vendorPath, corrupt);

    await ensureBinary({ ...fixture.options, packageRoot });

    assert.deepEqual(await fs.readFile(vendorPath), binary, "a damaged binary must not be accepted forever");
    assert.deepEqual(await listTempSiblings(vendorPath), []);
  });
}

test("a failed install leaves the previous complete binary in place", async (t) => {
  const packageRoot = await tempRoot(t, "agent-dump-keep-old-");
  const spec = getBinarySpec("linux", "x64");
  const vendorPath = getVendorBinaryPath(packageRoot, spec);
  const previous = Buffer.from("#!/usr/bin/env bash\necho previous\n", "utf8");
  const version = "0.6.13";

  await fs.mkdir(path.dirname(vendorPath), { recursive: true });
  await fs.writeFile(vendorPath, previous);

  await assert.rejects(
    ensureBinary({
      packageRoot,
      platform: "linux",
      arch: "x64",
      version,
      // 期望的是新版本，既有文件因此校验失败并触发重装；重装本身再失败
      checksums: { [version]: { [spec.target]: "0".repeat(64) } },
      runNpmImpl: async () => {
        throw new Error("registry unreachable");
      }
    })
  );

  assert.deepEqual(await fs.readFile(vendorPath), previous, "旧的完整 binary 不得在失败路径上被删掉");
  assert.deepEqual(await listTempSiblings(vendorPath), []);
});

test("publishBinaryAtomically never leaves a partial file at the final path", async (t) => {
  const packageRoot = await tempRoot(t, "agent-dump-atomic-");
  const spec = getBinarySpec("linux", "x64");
  const vendorPath = getVendorBinaryPath(packageRoot, spec);
  const previous = Buffer.from("old-complete-binary", "utf8");

  await fs.mkdir(path.dirname(vendorPath), { recursive: true });
  await fs.writeFile(vendorPath, previous);

  const originalRename = fs.rename;
  fs.rename = async () => {
    // 在替换的那一刻观察最终路径：它必须还是旧的完整文件，不能是半截新文件
    assert.deepEqual(await fs.readFile(vendorPath), previous);
    throw Object.assign(new Error("interrupted"), { code: "EIO" });
  };

  try {
    await assert.rejects(publishBinaryAtomically(vendorPath, Buffer.from("new-complete-binary", "utf8")));
  } finally {
    fs.rename = originalRename;
  }

  assert.deepEqual(await fs.readFile(vendorPath), previous);
  assert.deepEqual(await listTempSiblings(vendorPath), [], "失败时本次临时文件必须清理");
});

test("concurrent installs of the same version converge without leftovers", async (t) => {
  const packageRoot = await tempRoot(t, "agent-dump-concurrent-");
  const binary = Buffer.from("#!/usr/bin/env bash\necho concurrent\n", "utf8");
  const fixture = await buildInstallFixture(packageRoot, binary);
  const vendorPath = getVendorBinaryPath(packageRoot, fixture.spec);

  const results = await Promise.all(
    Array.from({ length: 6 }, () => installBinary({ ...fixture.options, packageRoot }))
  );

  assert.deepEqual(new Set(results), new Set([vendorPath]));
  assert.deepEqual(await fs.readFile(vendorPath), binary);
  assert.deepEqual(await listTempSiblings(vendorPath), [], "并发安装不得留下临时文件");
});

test("a locked target reports that the binary is in use instead of corrupting it", async (t) => {
  const packageRoot = await tempRoot(t, "agent-dump-locked-");
  const spec = getBinarySpec("linux", "x64");
  const vendorPath = getVendorBinaryPath(packageRoot, spec);
  const previous = Buffer.from("running-binary", "utf8");

  await fs.mkdir(path.dirname(vendorPath), { recursive: true });
  await fs.writeFile(vendorPath, previous);

  const originalRename = fs.rename;
  // Windows 上正在执行的 binary 会锁住目标路径
  fs.rename = async () => {
    throw Object.assign(new Error("locked"), { code: "EPERM" });
  };

  try {
    await assert.rejects(publishBinaryAtomically(vendorPath, Buffer.from("new", "utf8")), /it is in use/);
  } finally {
    fs.rename = originalRename;
  }

  assert.deepEqual(await fs.readFile(vendorPath), previous);
  assert.deepEqual(await listTempSiblings(vendorPath), []);
});
