import { expect, test } from "@playwright/test";

const guides = [
  { home: "/", path: "/guides/export-codex-session/", lang: "en", title: "Export a Codex session to Markdown" },
  { home: "/zh/", path: "/zh/guides/export-codex-session/", lang: "zh-Hans", title: "将 Codex 会话导出为 Markdown" },
];

for (const guide of guides) {
  test(`${guide.lang} guide has crawlable content and reciprocal translations`, async ({ page, request }) => {
    await page.route("https://umami.xingkaixin.me/**", (route) => route.abort());
    await page.goto(guide.home);
    await page.locator(`#hero a[href="${guide.path}"]`).click();
    await expect(page).toHaveURL(guide.path);
    await expect(page).toHaveTitle(`${guide.title} | Agent Dump`);
    await expect(page.locator("h1")).toHaveText(guide.title);
    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href", `https://agent-dump.xingkaixin.me${guide.path}`);
    await expect(page.locator('link[rel="alternate"]')).toHaveCount(3);
    for (const translation of guides) {
      await expect(page.locator(`link[hreflang="${translation.lang}"]`)).toHaveAttribute("href", `https://agent-dump.xingkaixin.me${translation.path}`);
      await expect(page.locator(`header a[lang="${translation.lang}"]`)).toHaveAttribute("href", translation.path);
    }
    await expect(page.locator('header a[href$="#install"]')).toHaveAttribute("href", `${guide.home}#install`);

    const response = await request.get(guide.path);
    expect(response.ok()).toBe(true);
    const html = await response.text();
    expect(html).toContain("YOUR_SESSION_ID");
    expect(html).toContain("./exports/codex/");
    const schema = JSON.parse(await page.locator('script[type="application/ld+json"]').innerText());
    expect(schema["@graph"]).toContainEqual(expect.objectContaining({ "@type": "WebPage", url: `https://agent-dump.xingkaixin.me${guide.path}` }));
    expect(schema["@graph"].some((node: { "@type": string }) => node["@type"] === "FAQPage")).toBe(false);
    expect(await (await request.get("/sitemap-0.xml")).text()).toContain(`<loc>https://agent-dump.xingkaixin.me${guide.path}</loc>`);

    for (const width of [360, 1280]) {
      await page.setViewportSize({ width, height: 844 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
      await expect(page.locator("article h2").first()).toBeVisible();
    }
    await page.locator('header a[href$="#install"]').click();
    await expect(page.locator("#install")).toBeVisible();
  });
}
