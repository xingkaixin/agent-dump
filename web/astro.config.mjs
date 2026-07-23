// @ts-check
import { readFileSync } from "node:fs";
import { defineConfig } from "astro/config";
import react from "@astrojs/react";
import sitemap from "@astrojs/sitemap";
import icon from "astro-icon";
import tailwindcss from "@tailwindcss/vite";

// Version single source of truth is the Python package metadata. Resolved from this
// config's fixed location and inlined at build time (see src/lib/version.ts).
const aboutSource = readFileSync(
  new URL("../src/agent_dump/__about__.py", import.meta.url),
  "utf8",
);
const versionMatch = aboutSource.match(/__version__\s*=\s*"([^"]+)"/);
if (!versionMatch) {
  throw new Error("Could not read __version__ from src/agent_dump/__about__.py");
}
const version = versionMatch[1];

// https://astro.build/config
export default defineConfig({
  site: "https://agent-dump.xingkaixin.me",
  // `en` serves from `/`, `zh` from `/zh/` — preserves the existing URL contract.
  i18n: {
    defaultLocale: "en",
    locales: ["en", "zh"],
    routing: { prefixDefaultLocale: false },
  },
  integrations: [
    react(),
    icon(),
    sitemap({
      i18n: {
        defaultLocale: "en",
        locales: { en: "en", zh: "zh-Hans" },
      },
    }),
  ],
  vite: {
    plugins: [tailwindcss()],
    define: {
      __AGENT_DUMP_VERSION__: JSON.stringify(version),
    },
  },
});
