import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import fs from "node:fs/promises";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import zlib from "node:zlib";

const require = createRequire(import.meta.url);
const {
  DEFAULT_IDLE_TIMEOUT_MS,
  DEFAULT_TOTAL_TIMEOUT_MS,
  MAX_COMPRESSED_TARBALL_BYTES,
  MAX_DECOMPRESSED_TAR_BYTES,
  MAX_METADATA_BYTES,
  ensureBinary,
  extractBinaryFromTarball,
  fetchBuffer,
  getRegistryBaseUrl,
  getVendorBinaryPath,
  installBinary,
  sha256,
  withRetries
} = require("../packages/cli/lib/install-binary.cjs");
const { getBinarySpec } = require("../packages/cli/lib/targets.cjs");

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

test("getRegistryBaseUrl prefers explicit environment and strips trailing slashes", () => {
  assert.equal(
    getRegistryBaseUrl({
      AGENT_DUMP_NPM_REGISTRY_URL: "http://127.0.0.1:4873///",
      npm_config_registry: "https://registry.npmjs.org/"
    }),
    "http://127.0.0.1:4873"
  );
});

test("extractBinaryFromTarball reads the packaged executable from the tarball", () => {
  const spec = getBinarySpec("win32", "x64");
  const binary = Buffer.from("fake-exe");
  const tarball = createTarGz([
    { name: "package/package.json", content: Buffer.from('{"name":"@agent-dump/cli-win32-x64"}') },
    { name: "package/bin/agent-dump.exe", content: binary }
  ]);

  assert.deepEqual(extractBinaryFromTarball(tarball, spec), binary);
});

test("installBinary downloads, verifies and writes the vendored binary", async () => {
  const packageRoot = await fs.mkdtemp(path.join(os.tmpdir(), "agent-dump-install-"));
  const version = "0.6.13";
  const spec = getBinarySpec("linux", "x64");
  const binary = Buffer.from("#!/usr/bin/env bash\necho help\n", "utf8");
  const tarball = createTarGz([
    { name: "package/package.json", content: Buffer.from('{"name":"@agent-dump/cli-linux-x64"}') },
    { name: "package/bin/agent-dump", content: binary }
  ]);
  const metadataUrl = "http://registry.test/%40agent-dump%2Fcli-linux-x64";
  const tarballUrl = "http://registry.test/tarballs/cli-linux-x64-0.6.13.tgz";
  const seenUrls = [];

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
    retries: 1,
    fetchBufferImpl: async (url) => {
      seenUrls.push(url);
      if (url === metadataUrl) {
        return Buffer.from(
          JSON.stringify({
            versions: {
              [version]: {
                dist: {
                  tarball: tarballUrl
                }
              }
            }
          })
        );
      }

      if (url === tarballUrl) {
        return tarball;
      }

      throw new Error(`Unexpected URL: ${url}`);
    },
    registryBaseUrl: "http://registry.test"
  });

  assert.deepEqual(seenUrls, [metadataUrl, tarballUrl]);
  assert.equal(vendorPath, getVendorBinaryPath(packageRoot, spec));
  assert.deepEqual(await fs.readFile(vendorPath), binary);
});

test("installBinary fails on checksum mismatch", async () => {
  const packageRoot = await fs.mkdtemp(path.join(os.tmpdir(), "agent-dump-install-mismatch-"));
  const version = "0.6.13";
  const spec = getBinarySpec("win32", "x64");
  const tarball = createTarGz([
    { name: "package/package.json", content: Buffer.from('{"name":"@agent-dump/cli-win32-x64"}') },
    { name: "package/bin/agent-dump.exe", content: Buffer.from("bad-binary") }
  ]);

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
      retries: 1,
      fetchBufferImpl: async (url) => {
        if (url.includes("%40agent-dump%2Fcli-win32-x64")) {
          return Buffer.from(
            JSON.stringify({
              versions: {
                [version]: {
                  dist: {
                    tarball: "http://registry.test/tarballs/cli-win32-x64-0.6.13.tgz"
                  }
                }
              }
            })
          );
        }

        return tarball;
      },
      registryBaseUrl: "http://registry.test"
    }),
    /Checksum mismatch/
  );
});

test("ensureBinary returns the existing vendored binary without downloading", async () => {
  const packageRoot = await fs.mkdtemp(path.join(os.tmpdir(), "agent-dump-ensure-existing-"));
  const spec = getBinarySpec("linux", "x64");
  const vendorPath = getVendorBinaryPath(packageRoot, spec);

  await fs.mkdir(path.dirname(vendorPath), { recursive: true });
  await fs.writeFile(vendorPath, "existing-binary", "utf8");

  const ensuredPath = await ensureBinary({
    packageRoot,
    platform: "linux",
    arch: "x64",
    fetchBufferImpl: async () => {
      throw new Error("ensureBinary should not download when the binary already exists");
    }
  });

  assert.equal(ensuredPath, vendorPath);
  assert.equal(await fs.readFile(vendorPath, "utf8"), "existing-binary");
});

test("ensureBinary installs the vendored binary when it is missing", async () => {
  const packageRoot = await fs.mkdtemp(path.join(os.tmpdir(), "agent-dump-ensure-install-"));
  const version = "0.6.13";
  const spec = getBinarySpec("linux", "x64");
  const binary = Buffer.from("#!/usr/bin/env bash\necho installed\n", "utf8");
  const tarball = createTarGz([
    { name: "package/package.json", content: Buffer.from('{"name":"@agent-dump/cli-linux-x64"}') },
    { name: "package/bin/agent-dump", content: binary }
  ]);

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
    retries: 1,
    fetchBufferImpl: async (url) => {
      if (url.includes("%40agent-dump%2Fcli-linux-x64")) {
        return Buffer.from(
          JSON.stringify({
            versions: {
              [version]: {
                dist: {
                  tarball: "http://registry.test/tarballs/cli-linux-x64-0.6.13.tgz"
                }
              }
            }
          })
        );
      }

      return tarball;
    },
    registryBaseUrl: "http://registry.test"
  });

  assert.equal(ensuredPath, getVendorBinaryPath(packageRoot, spec));
  assert.deepEqual(await fs.readFile(ensuredPath), binary);
});

// AD-168：下载与解压都必须有硬上限，停滞的响应要能真正终止并进入重试
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

async function expectRejection(promise) {
  try {
    await promise;
  } catch (error) {
    return error;
  }
  assert.fail("expected the request to be rejected");
}

test("fetchBuffer rejects a response that never sends headers", async () => {
  await withServer(
    () => {},
    async (url) => {
      const error = await expectRejection(fetchBuffer(url, { idleTimeoutMs: 150 }));
      assert.match(error.message, /No data for 150ms/);
    }
  );
});

test("fetchBuffer rejects a response that stalls after headers", async () => {
  await withServer(
    (req, res) => {
      res.writeHead(200);
      res.write("partial");
    },
    async (url) => {
      const error = await expectRejection(fetchBuffer(url, { idleTimeoutMs: 150 }));
      assert.match(error.message, /No data for 150ms/);
    }
  );
});

test("fetchBuffer rejects an oversized declared Content-Length", async () => {
  await withServer(
    (req, res) => {
      res.writeHead(200, { "content-length": "999999" });
      res.end(Buffer.alloc(10));
    },
    async (url) => {
      const error = await expectRejection(fetchBuffer(url, { maxBytes: 1000 }));
      assert.match(error.message, /declares 999999 bytes/);
    }
  );
});

test("fetchBuffer rejects a chunked body that lies about its size", async () => {
  await withServer(
    (req, res) => {
      res.writeHead(200);
      res.end(Buffer.alloc(5000));
    },
    async (url) => {
      const error = await expectRejection(fetchBuffer(url, { maxBytes: 1000 }));
      assert.match(error.message, /exceeded the 1000 byte limit/);
    }
  );
});

test("fetchBuffer rejects an aborted connection", async () => {
  await withServer(
    (req, res) => {
      res.writeHead(200);
      res.write(Buffer.alloc(16));
      res.destroy();
    },
    async (url) => {
      const error = await expectRejection(fetchBuffer(url, { idleTimeoutMs: 5000 }));
      assert.ok(error instanceof Error);
    }
  );
});

test("a timed out request settles so the existing retry loop can run", async () => {
  await withServer(
    (req, res) => {
      res.writeHead(200);
      res.write("partial");
    },
    async (url) => {
      let attempts = 0;
      const error = await expectRejection(
        withRetries(
          () => {
            attempts += 1;
            return fetchBuffer(url, { idleTimeoutMs: 60 });
          },
          { retries: 3, delayMs: 1 }
        )
      );
      assert.equal(attempts, 3, "a hung request never rejects, so retries never run");
      assert.match(error.message, /No data for 60ms/);
    }
  );
});

test("redirects inherit the original deadline instead of resetting it", async () => {
  await withServer(
    (req, res) => {
      if (req.url === "/artifact") {
        res.writeHead(302, { location: "/next" });
        res.end();
        return;
      }
      res.writeHead(200);
      res.write("partial");
    },
    async (url) => {
      const started = Date.now();
      const error = await expectRejection(fetchBuffer(url, { totalTimeoutMs: 200, idleTimeoutMs: 5000 }));
      assert.ok(Date.now() - started < 1500, "the redirect must not restart the total budget");
      assert.match(error.message, /Timed out/);
    }
  );
});

test("fetchBuffer still returns a normal response unchanged", async () => {
  await withServer(
    (req, res) => {
      res.writeHead(200);
      res.end("payload");
    },
    async (url) => {
      assert.equal((await fetchBuffer(url)).toString(), "payload");
    }
  );
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
  assert.ok(MAX_METADATA_BYTES > 0);
  assert.ok(MAX_COMPRESSED_TARBALL_BYTES > 0);
  assert.ok(MAX_DECOMPRESSED_TAR_BYTES > MAX_COMPRESSED_TARBALL_BYTES);
  assert.ok(DEFAULT_IDLE_TIMEOUT_MS > 0);
  assert.ok(DEFAULT_TOTAL_TIMEOUT_MS > DEFAULT_IDLE_TIMEOUT_MS);
});
