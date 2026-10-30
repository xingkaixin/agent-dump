import { readdir, readFile } from "node:fs/promises";
import { extname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const dist = fileURLToPath(new URL("../dist/", import.meta.url));
const origin = "http://fonts.localhost";
const families = ["Montserrat Variable", "IBM Plex Mono"];

const files = await readdir(dist, { recursive: true });
const pages = files
  .filter((file) => file.endsWith(".html"))
  .map((file) => `/${file.replace(/index\.html$/, "")}`)
  .sort();
const scriptChars = new Set();
for (const file of files.filter((file) => file.startsWith("_astro/") && file.endsWith(".js"))) {
  for (const char of await readFile(join(dist, file), "utf8")) {
    if (char.codePointAt(0) > 0x7e) scriptChars.add(char);
  }
}

const usage = Object.fromEntries(
  families.map((family) => [family, { chars: new Set(), features: new Set() }]),
);
const browser = await chromium.launch();
try {
  for (const viewport of [{ width: 1280, height: 900 }, { width: 390, height: 844 }]) {
    const context = await browser.newContext({ viewport });
    await context.route("**/*", async (route) => {
      const url = new URL(route.request().url());
      if (url.origin !== origin) return route.abort();
      let path = join(dist, decodeURIComponent(url.pathname));
      if (!extname(path)) path = join(path, "index.html");
      if (relative(dist, path).startsWith("..")) return route.fulfill({ status: 404 });
      try {
        await route.fulfill({ path });
      } catch {
        await route.fulfill({ status: 404 });
      }
    });
    const page = await context.newPage();
    for (const path of pages) {
      await page.goto(origin + path, { waitUntil: "networkidle" });
      const found = await page.evaluate((families) => {
        const out = {};
        const record = (style, text) => {
          const family = style.fontFamily.split(",")[0].trim().replace(/^["']|["']$/g, "");
          if (!text.trim() || !families.includes(family)) return;
          const entry = (out[family] ??= { chars: "", features: [] });
          const transform = style.textTransform;
          entry.chars += transform === "uppercase" ? text.toUpperCase()
            : transform === "lowercase" ? text.toLowerCase()
            : transform === "capitalize" ? text + text.toUpperCase()
            : text;
          if (style.textOverflow === "ellipsis") entry.chars += "\u2026";
          if (style.hyphens === "auto") entry.chars += "\u2010";
          for (const [name, value] of [
            ["font-feature-settings", style.fontFeatureSettings],
            ["font-variant-ligatures", style.fontVariantLigatures],
            ["font-variant-numeric", style.fontVariantNumeric],
            ["font-variant-caps", style.fontVariantCaps],
            ["font-variant-position", style.fontVariantPosition],
            ["font-variant-alternates", style.fontVariantAlternates],
            ["font-variation-settings", style.fontVariationSettings],
            ["font-kerning", style.fontKerning],
          ]) {
            if (value && value !== "normal" && value !== "auto") entry.features.push(`${name}: ${value}`);
          }
        };
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        for (let node = walker.nextNode(); node; node = walker.nextNode()) {
          const parent = node.parentElement;
          if (parent && !parent.closest("script, style, noscript, template")) {
            record(getComputedStyle(parent), node.data);
          }
        }
        for (const element of document.body.querySelectorAll("*")) {
          for (const pseudo of ["::before", "::after", "::marker"]) {
            const style = getComputedStyle(element, pseudo);
            for (const [, text] of style.content.matchAll(/"((?:[^"\\]|\\.)*)"/g)) record(style, text);
          }
          if (element.placeholder) record(getComputedStyle(element, "::placeholder"), element.placeholder);
          if (element.matches("input, textarea") && element.value) record(getComputedStyle(element), element.value);
        }
        return out;
      }, families);
      for (const [family, entry] of Object.entries(found)) {
        const target = usage[family];
        for (const char of entry.chars) target.chars.add(char);
        for (const feature of entry.features) target.features.add(feature);
      }
    }
    await context.close();
  }
} finally {
  await browser.close();
}

const sorted = (set) => [...set].sort();
process.stdout.write(
  JSON.stringify({
    pages,
    scriptChars: sorted(scriptChars).join(""),
    families: Object.fromEntries(
      Object.entries(usage).map(([family, entry]) => [
        family,
        {
          chars: sorted(entry.chars).join(""),
          features: sorted(entry.features),
        },
      ]),
    ),
  }),
);
