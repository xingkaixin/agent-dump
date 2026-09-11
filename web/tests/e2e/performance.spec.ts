import { readFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("https://umami.xingkaixin.me/**", (route) => route.abort());
});

test("Pages hints reference the CSS and fonts used by each locale", async ({ page }) => {
  const headers = await readFile(new URL("../../dist/_headers", import.meta.url), "utf8");
  expect(headers).toContain("Cache-Control: public, max-age=31536000, immutable");

  for (const path of ["/", "/zh/", "/ja/"]) {
    await page.goto(path);
    await page.evaluate(() => document.fonts.ready);
    const rule = headers.split("\n\n").find((section) => section.startsWith(`${path}\n`));
    expect(rule).toBeDefined();

    const stylesheets = await page.locator('link[rel="stylesheet"]').evaluateAll(
      (links) => links.map((link) => link.getAttribute("href")),
    );
    expect(stylesheets.length).toBeGreaterThan(0);
    for (const href of stylesheets) {
      expect(rule).toContain(`<${href}>; rel=preload; as=style`);
      expect((await page.request.get(href!)).ok()).toBe(true);
    }

    const fonts = page.locator('link[rel="preload"][as="font"]');
    await expect(fonts).toHaveCount(2);
    const requests = await page.evaluate(() => performance.getEntriesByType("resource")
      .filter((entry) => new URL(entry.name).pathname.endsWith(".woff2"))
      .map((entry) => new URL(entry.name).pathname));
    expect(requests).toHaveLength(2);
    for (const font of await fonts.all()) {
      await expect(font).toHaveAttribute("crossorigin", "anonymous");
      const href = await font.getAttribute("href");
      expect(requests).toContain(href);
      expect(rule).toContain(`<${href}>; rel=preload; as=font; type="font/woff2"; crossorigin`);
    }
  }
});

test("hero content is visible while WebGL waits for page load", async ({ page }) => {
  let releaseScript!: () => void;
  const scriptReady = new Promise<void>((resolve) => { releaseScript = resolve; });
  await page.route("https://umami.xingkaixin.me/script.js", async (route) => {
    await scriptReady;
    await route.fulfill({ contentType: "application/javascript", body: "" });
  });
  const scene = page.locator("[data-focus-scene]");
  try {
    await page.goto("/", { waitUntil: "commit" });
    await expect(scene.locator(".focus-scene__fallback")).toBeVisible();
    await expect(page.locator(".hero-copy")).toHaveCSS("opacity", "1");
    await expect(page.locator(".hero-visual")).toHaveCSS("opacity", "1");
    await expect(scene).not.toHaveAttribute("data-ready", "true");
  } finally {
    releaseScript();
  }
  await expect(scene).toHaveAttribute("data-webgl", /^(ready|unavailable)$/);
});

test("WebGL pauses offscreen and respects reduced motion", async ({ page }) => {
  await page.addInitScript(() => {
    const draw = WebGLRenderingContext.prototype.drawArrays;
    WebGLRenderingContext.prototype.drawArrays = function (...args) {
      const root = document.documentElement;
      root.dataset.draws = String(Number(root.dataset.draws ?? 0) + 1);
      return draw.apply(this, args);
    };
  });
  await page.goto("/");
  const scene = page.locator("[data-focus-scene]");
  await expect(scene).toHaveAttribute("data-webgl", /^(ready|unavailable)$/);
  test.skip(await scene.getAttribute("data-webgl") === "unavailable", "WebGL is unavailable in this browser");

  const frameCounts = () => page.evaluate(async () => {
    const counts = [];
    for (let frame = 0; frame < 5; frame++) {
      await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
      counts.push(Number(document.documentElement.dataset.draws ?? 0));
    }
    return new Set(counts).size;
  });
  await expect.poll(frameCounts).toBeGreaterThan(1);
  await page.evaluate(() => window.scrollTo({ top: document.body.scrollHeight, behavior: "instant" }));
  await expect(scene).not.toBeInViewport();
  await expect.poll(frameCounts).toBe(1);

  await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
  await expect.poll(frameCounts).toBeGreaterThan(1);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect.poll(frameCounts).toBe(1);
  const draws = await page.locator("html").getAttribute("data-draws");
  await page.locator("[data-theme-toggle]").click();
  await expect.poll(() => page.locator("html").getAttribute("data-draws")).not.toBe(draws);
  await expect.poll(frameCounts).toBe(1);
});
