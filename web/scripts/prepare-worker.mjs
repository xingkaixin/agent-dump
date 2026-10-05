import { access, cp, mkdir, rm, writeFile } from "node:fs/promises";

const assets = new URL("../dist/", import.meta.url);
const output = new URL("../.cloudflare/output/", import.meta.url);
const worker = new URL("v0/workers/default/", output);

await access(new URL("index.html", assets));
await rm(output, { recursive: true, force: true });
await mkdir(worker, { recursive: true });
await writeFile(
  new URL("v0/config.json", output),
  JSON.stringify({ buildContext: { isPreview: false } }),
);
await writeFile(
  new URL("worker.config.json", worker),
  JSON.stringify({
    name: "agent-dump",
    compatibilityDate: "2026-10-05",
    assets: {
      htmlHandling: "auto-trailing-slash",
      notFoundHandling: "404-page",
    },
    domains: ["agent-dump.xingkaixin.me"],
  }),
);
await cp(assets, new URL("assets/", worker), { recursive: true });
