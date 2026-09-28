import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { NATIVE_TARGETS } from "./native-targets.mjs";

export async function generateDistribution(source, destination, version) {
  assert.match(version, /^\d+\.\d+\.\d+$/);
  const checksums = JSON.parse(await readFile(path.join(source, "agent-dump-binary-checksums.json"), "utf8"));
  const assets = [];
  for (const target of NATIVE_TARGETS) {
    const name = target.releaseAssetName;
    const hash = createHash("sha256").update(await readFile(path.join(source, name))).digest("hex");
    assert.equal(hash, checksums[version]?.[target.target], `Checksum mismatch: ${name}`);
    assets.push({ ...target, name, hash });
  }
  const stanza = (platform, arch, indent = 6) => {
    const { name, hash } = assets.find((asset) => asset.platform === platform && asset.arch === arch);
    return `url "https://github.com/xingkaixin/agent-dump/releases/download/v${version}/${name}"
${" ".repeat(indent)}sha256 "${hash}"`;
  };
  await mkdir(destination, { recursive: true });
  await writeFile(path.join(destination, "SHA256SUMS"), assets.map(({ name, hash }) => `${hash}  ${name}\n`).join(""));
  await writeFile(path.join(destination, "agent-dump.rb"), `class AgentDump < Formula
  desc "Export and search AI coding assistant sessions"
  homepage "https://github.com/xingkaixin/agent-dump"
  version "${version}"
  license "MIT"

  on_macos do
    on_arm do
      ${stanza("darwin", "arm64")}
    end
    on_intel do
      ${stanza("darwin", "x64")}
    end
  end

  on_linux do
    depends_on arch: :x86_64
    ${stanza("linux", "x64", 4)}
  end

  def install
    bin.install Dir["agent-dump-*"].fetch(0) => "agent-dump"
  end

  test do
    assert_match "agent-dump #{version}", shell_output("#{bin}/agent-dump --version")
    assert_match "Usage:", shell_output("#{bin}/agent-dump --help")
  end
end
`);
  const windows = assets.find((asset) => asset.platform === "win32" && asset.arch === "x64");
  await writeFile(path.join(destination, "agent-dump.json"), `${JSON.stringify({
    version,
    description: "Export and search AI coding assistant sessions",
    homepage: "https://github.com/xingkaixin/agent-dump",
    license: "MIT",
    architecture: {
      "64bit": {
        url: `https://github.com/xingkaixin/agent-dump/releases/download/v${version}/${windows.name}#/agent-dump.exe`,
        hash: windows.hash,
      },
    },
    bin: "agent-dump.exe",
  }, null, 2)}\n`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const [source, destination, version] = process.argv.slice(2);
  assert.ok(source && destination && version, "Usage: node npm/scripts/distribution.mjs <source> <destination> <version>");
  await generateDistribution(source, destination, version);
}
