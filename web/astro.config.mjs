// @ts-check
import { readFileSync } from "node:fs";
import { appendFile, readFile } from "node:fs/promises";
import { defineConfig } from "astro/config";
import react from "@astrojs/react";
import sitemap from "@astrojs/sitemap";
import tailwindcss from "@tailwindcss/vite";

const cargoSource = readFileSync(
  new URL("../Cargo.toml", import.meta.url),
  "utf8",
);
const versionMatch = cargoSource.match(/^version\s*=\s*"([^"]+)"/m);
if (!versionMatch) {
  throw new Error("Could not read package version from Cargo.toml");
}
const version = versionMatch[1];

// https://astro.build/config
export default defineConfig({
  site: "https://agent-dump.xingkaixin.me",
  // `en` serves from `/`; translated locales use stable, prefixed paths.
  i18n: {
    defaultLocale: "en",
    locales: ["en", "zh", "ja"],
    routing: { prefixDefaultLocale: false },
  },
  integrations: [
    react(),
    sitemap({
      i18n: {
        defaultLocale: "en",
        locales: { en: "en", zh: "zh-Hans", ja: "ja" },
      },
    }),
    {
      name: "pages-early-hints",
      hooks: {
        "astro:build:done": async ({ dir, assets }) => {
          const headers = [];
          for (const file of [...assets.values()].flat()) {
            if (!file.pathname.endsWith(".html")) continue;
            const html = await readFile(file, "utf8");
            const hints = [];
            for (const [link] of html.matchAll(/<link\b[^>]*>/g)) {
              const href = link.match(/\bhref="([^"]+)"/)?.[1];
              if (!href) continue;
              if (/\brel="stylesheet"/.test(link)) {
                hints.push(`<${href}>; rel=preload; as=style`);
              } else if (/\brel="preload"/.test(link) && /\bas="font"/.test(link)) {
                hints.push(`<${href}>; rel=preload; as=font; type="font/woff2"; crossorigin`);
              }
            }
            if (!hints.length) continue;
            const path = file.pathname.slice(dir.pathname.length).replace(/index\.html$/, "");
            headers.push(`/${path}\n  Link: ${hints.join(", ")}\n`);
          }
          await appendFile(new URL("_headers", dir), `\n${headers.join("\n")}`);
        },
      },
    },
  ],
  vite: {
    plugins: [tailwindcss()],
    define: {
      __AGENT_DUMP_VERSION__: JSON.stringify(version),
    },
  },
});
