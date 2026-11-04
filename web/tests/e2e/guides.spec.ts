import { expect, test } from "@playwright/test";

test("all articles and their internal links are reachable", async ({
  page,
  request,
}) => {
  for (const prefix of ["", "/zh"]) {
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
