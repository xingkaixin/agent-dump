import { expect, test } from "@playwright/test";

const guides = [
  {
    home: "/",
    path: "/guides/export-codex-session/",
    lang: "en",
    title: "Export a Codex session to Markdown",
  },
  {
    home: "/zh/",
    path: "/zh/guides/export-codex-session/",
    lang: "zh-Hans",
    title: "将 Codex 会话导出为 Markdown",
  },
];

for (const guide of guides) {
  test(`${guide.lang} guide has crawlable content and reciprocal translations`, async ({
    page,
    request,
  }) => {
    await page.route("https://umami.xingkaixin.me/**", (route) =>
      route.abort(),
    );
    await page.goto(guide.home);
    await page.locator(`#hero a[href="${guide.path}"]`).click();
    await expect(page).toHaveURL(guide.path);
    await expect(page).toHaveTitle(`${guide.title} | Agent Dump`);
    await expect(page.locator("h1")).toHaveText(guide.title);
    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
      "href",
      `https://agent-dump.xingkaixin.me${guide.path}`,
    );
    await expect(page.locator('link[rel="alternate"]')).toHaveCount(3);
    for (const translation of guides) {
      await expect(
        page.locator(`link[hreflang="${translation.lang}"]`),
      ).toHaveAttribute(
        "href",
        `https://agent-dump.xingkaixin.me${translation.path}`,
      );
      await expect(
        page.locator(`header a[lang="${translation.lang}"]`),
      ).toHaveAttribute("href", translation.path);
    }
    await expect(page.locator('.site-nav a[href$="#install"]')).toHaveAttribute(
      "href",
      `${guide.home}#install`,
    );

    const response = await request.get(guide.path);
    expect(response.ok()).toBe(true);
    const html = await response.text();
    expect(html).toContain("YOUR_SESSION_ID");
    expect(html).toContain("./exports/codex/");
    const schema = JSON.parse(
      await page.locator('script[type="application/ld+json"]').innerText(),
    );
    expect(schema["@graph"]).toContainEqual(
      expect.objectContaining({
        "@type": "WebPage",
        url: `https://agent-dump.xingkaixin.me${guide.path}`,
      }),
    );
    expect(
      schema["@graph"].some(
        (node: { "@type": string }) => node["@type"] === "FAQPage",
      ),
    ).toBe(false);
    expect(await (await request.get("/sitemap-0.xml")).text()).toContain(
      `<loc>https://agent-dump.xingkaixin.me${guide.path}</loc>`,
    );

    for (const width of [360, 1280]) {
      await page.setViewportSize({ width, height: 844 });
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth),
      ).toBe(width);
      await expect(page.locator("article h2").first()).toBeVisible();
    }
    await page.locator('.site-nav a[href$="#install"]').click();
    await expect(page.locator("#install")).toBeVisible();
  });
}

test("guide filters combine category and query, and recover from empty results", async ({
  page,
}) => {
  await page.goto("/zh/guides/");
  await expect(page.locator(".guide-card:visible")).toHaveCount(6);
  await page.getByRole("button", { name: "导出与归档", exact: true }).click();
  await expect(page.locator(".guide-card:visible")).toHaveCount(3);
  await page.getByRole("searchbox", { name: "搜索指南" }).fill("Claude");
  await expect(page.locator(".guide-card:visible")).toHaveCount(2);
  await page.getByRole("searchbox").fill("no-such-guide");
  await expect(page.getByRole("status")).toContainText("没有匹配的指南");
  await page.getByRole("searchbox").fill("");
  await page.getByRole("button", { name: "全部指南", exact: true }).click();
  await expect(page.locator(".guide-card:visible")).toHaveCount(6);
  await expect(page.getByRole("status")).toBeHidden();
});

test("all articles have indexable HTML, article metadata and working internal links", async ({
  page,
  request,
}) => {
  const sitemap = await (await request.get("/sitemap-0.xml")).text();
  for (const prefix of ["", "/zh"]) {
    await page.goto(`${prefix}/guides/`);
    const paths = await page
      .locator(".guide-card > a")
      .evaluateAll((links) => links.map((link) => link.getAttribute("href")!));
    expect(paths).toHaveLength(6);
    for (const path of paths) {
      await page.goto(path);
      await expect(page.locator("main h1")).toHaveCount(1);
      await expect(page.locator('meta[property="og:type"]')).toHaveAttribute(
        "content",
        "article",
      );
      await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
        "href",
        `https://agent-dump.xingkaixin.me${path}`,
      );
      const schema = JSON.parse(
        await page.locator('script[type="application/ld+json"]').innerText(),
      );
      expect(schema["@graph"]).toContainEqual(
        expect.objectContaining({
          "@type": "Article",
          headline: await page.locator("main h1").innerText(),
        }),
      );
      expect(schema["@graph"]).toContainEqual(
        expect.objectContaining({ "@type": "BreadcrumbList" }),
      );
      expect(sitemap).toContain(
        `<loc>https://agent-dump.xingkaixin.me${path}</loc>`,
      );
      const response = await request.get(path);
      expect(await response.text()).toContain("agent-dump");
      const links = await page
        .locator('main a[href^="/"]')
        .evaluateAll((elements) =>
          elements.map((el) => el.getAttribute("href")!),
        );
      for (const href of new Set(links)) {
        expect((await request.get(href)).ok(), href).toBe(true);
      }
      const toc = await page
        .locator(".guide-toc a")
        .evaluateAll((links) =>
          links.map((a) => a.getAttribute("href")!.slice(1)),
        );
      for (const id of toc)
        expect(
          await page.evaluate(
            (id) => Boolean(document.getElementById(decodeURIComponent(id))),
            id,
          ),
        ).toBe(true);
    }
  }
});

test("article commands copy as plain text", async ({ context, page }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("/zh/guides/handoff-context-to-ai-agent/");
  const block = page.locator(".guide-code").first();
  await block.getByRole("button", { name: "复制", exact: true }).click();
  await expect(block.getByRole("status")).toHaveText("已复制");
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
    await block.locator("code").textContent(),
  );
});
