import { readFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("https://umami.xingkaixin.me/**", (route) => route.abort());
});

test("Static asset hints reference the CSS and fonts used by each locale", async ({
  page,
}) => {
  const headers = await readFile(
    new URL("../../dist/_headers", import.meta.url),
    "utf8",
  );
  expect(headers).toContain(
    "Cache-Control: public, max-age=31536000, immutable",
  );

  for (const path of ["/", "/zh/", "/ja/"]) {
    await page.goto(path);
    await page.evaluate(() => document.fonts.ready);
    const rule = headers
      .split("\n\n")
      .find((section) => section.startsWith(`${path}\n`));
    expect(rule).toBeDefined();

    const stylesheets = await page
      .locator('link[rel="stylesheet"]')
      .evaluateAll((links) => links.map((link) => link.getAttribute("href")));
    expect(stylesheets.length).toBeGreaterThan(0);
    for (const href of stylesheets) {
      expect(rule).toContain(`<${href}>; rel=preload; as=style`);
      expect((await page.request.get(href!)).ok()).toBe(true);
    }

    const fonts = page.locator('link[rel="preload"][as="font"]');
    await expect(fonts).toHaveCount(2);
    const requests = await page.evaluate(() =>
      performance
        .getEntriesByType("resource")
        .filter((entry) => new URL(entry.name).pathname.endsWith(".woff2"))
        .map((entry) => new URL(entry.name).pathname),
    );
    expect(requests).toHaveLength(2);
    for (const font of await fonts.all()) {
      await expect(font).toHaveAttribute("crossorigin", "anonymous");
      const href = await font.getAttribute("href");
      expect(requests).toContain(href);
      expect(rule).toContain(
        `<${href}>; rel=preload; as=font; type="font/woff2"; crossorigin`,
      );
    }
  }
});

test("hero artwork is available without JavaScript and stays within its transfer budget", async ({
  browser,
  request,
}) => {
  const context = await browser.newContext({
    javaScriptEnabled: false,
    viewport: { width: 390, height: 844 },
  });
  const page = await context.newPage();
  await page.goto("/");
  await expect(page.locator("#hero h1")).toBeVisible();
  await expect(page.locator("#hero a[href='#install']")).toBeInViewport();
  const art = page.locator(".hero-art");
  await expect
    .poll(() => art.evaluate((image: HTMLImageElement) => image.naturalWidth))
    .toBeGreaterThan(0);
  const source = await art.evaluate(
    (image: HTMLImageElement) => image.currentSrc,
  );
  const response = await request.get(source);
  expect(response.headers()["content-type"]).toContain("image/webp");
  expect((await response.body()).byteLength).toBeLessThan(100 * 1024);
  await page.goto("/zh/guides/");
  await expect(page.locator(".guide-card")).toHaveCount(6);
  await expect(page.locator(".guide-card").first()).toBeVisible();
  await expect(page.locator(".guide-filters")).toBeHidden();
  await context.close();
});

test("reduced motion keeps the hero and revealed content static", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await expect(page.locator(".hero-art")).toHaveCSS("animation-name", "none");
  for (const section of ["#capabilities", "#guides", "#install"]) {
    await page.locator(section).scrollIntoViewIfNeeded();
    await expect(
      page.locator(section).locator("[data-reveal]").first(),
    ).toHaveCSS("opacity", "1");
  }
});
