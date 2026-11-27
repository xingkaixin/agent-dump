import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("https://umami.xingkaixin.me/**", (route) => route.abort());
});

test("all articles and their internal links are reachable", async ({
  page,
  request,
}) => {
  for (const prefix of ["", "/zh", "/ja"]) {
    await page.goto(`${prefix}/guides/`);
    const paths = await page
      .locator(".guide-card > a")
      .evaluateAll((links) => links.map((link) => link.getAttribute("href")!));
    expect(paths.length).toBeGreaterThan(0);
    for (const path of paths) {
      const response = await page.goto(path);
      expect(response?.ok(), path).toBe(true);
      const links = await page
        .locator('main a[href^="/"]')
        .evaluateAll((elements) =>
          elements.map((el) => el.getAttribute("href")!),
        );
      for (const href of new Set(links)) {
        expect((await request.get(href)).ok(), href).toBe(true);
      }
    }
  }
});

test("guide quick-install card copies commands and FAQ emits JSON-LD", async ({
  context,
  page,
}) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("/guides/export-cursor-chat-history/");

  const installBox = page.locator("[data-guide-install]");
  await expect(installBox).toBeVisible();
  await installBox.getByRole("button", { name: "npx", exact: true }).click();
  await installBox.locator("[data-ginst-copy]").click();
  await expect
    .poll(() => page.evaluate(() => navigator.clipboard.readText()))
    .toBe("npx @agent-dump/cli list --days 30");

  const jsonLdText = await page
    .locator('script[type="application/ld+json"]')
    .textContent();
  const jsonLd = JSON.parse(jsonLdText ?? "{}");
  const faq = jsonLd["@graph"]?.find(
    (node: { "@type"?: string }) => node["@type"] === "FAQPage",
  );
  expect(faq?.mainEntity?.length).toBeGreaterThan(0);
});
