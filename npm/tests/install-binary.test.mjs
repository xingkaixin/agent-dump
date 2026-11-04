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
  ensureBinary,
  getVendorBinaryPath,
  installBinary,
  publishBinaryAtomically,
  sha256
} = require("../packages/cli/lib/install-binary.cjs");
const { getBinarySpec } = require("../packages/cli/lib/targets.cjs");

// 每个临时根都在创建时就注册清理：node:test 的 t.after() 在成功、assert 失败与
// Promise reject 后都会执行，靠 finally 要在每个用例里各写一遍，靠进程退出则什么都不清。
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

test("ensureBinary repairs a damaged vendored binary", async (t) => {
  const packageRoot = await tempRoot(t, "agent-dump-repair-");
  const binary = Buffer.from("#!/usr/bin/env bash\necho repaired\n", "utf8");
  const fixture = await buildInstallFixture(packageRoot, binary);
  const vendorPath = getVendorBinaryPath(packageRoot, fixture.spec);

  await fs.mkdir(path.dirname(vendorPath), { recursive: true });
  await fs.writeFile(vendorPath, Buffer.from("#!/usr/bin", "utf8"));

  await ensureBinary({ ...fixture.options, packageRoot });

  assert.deepEqual(await fs.readFile(vendorPath), binary, "a damaged binary must not be accepted forever");
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

