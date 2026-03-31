import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import zlib from "node:zlib";

const require = createRequire(import.meta.url);
const {
  ensureBinary,
  extractBinaryFromTarball,
  getRegistryBaseUrl,
  getVendorBinaryPath,
  installBinary,
  sha256
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
