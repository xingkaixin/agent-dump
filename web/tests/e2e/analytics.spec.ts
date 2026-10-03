import { expect, test } from "@playwright/test";

test("successful copies record intent without command or conversation contents", async ({ context, page }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  const events: unknown[] = [];
  page.on("console", (message) => {
    if (message.type() === "info") events.push(JSON.parse(message.text()));
  });
  await page.route("https://umami.xingkaixin.me/script.js", (route) =>
    route.fulfill({
      contentType: "application/javascript",
      body: `window.umami = { track: async (name, data) => console.info(JSON.stringify({name, data})) };`,
    }),
  );
  await page.goto("/zh/#install");
  await page.getByRole("tab", { name: "npm", exact: true }).click();
  const panel = page.getByRole("tabpanel").filter({ hasText: "npm install" });
  await panel.getByRole("button", { name: "复制", exact: true }).click();
  await expect(panel.getByRole("status")).toHaveText("已复制");
  expect(events).toEqual([
    { name: "install-copy", data: { locale: "zh-Hans", method: "npm" } },
  ]);

  await page.goto("/guides/export-codex-session/");
  await page.locator(".guide-copy").first().click();
  await expect(page.locator(".guide-code [role=status]").first()).toHaveText("Copied");
  expect(events).toEqual([
    { name: "install-copy", data: { locale: "zh-Hans", method: "npm" } },
    { name: "guide-copy", data: { locale: "en" } },
  ]);
});

test("copy failures are not conversions and analytics failures do not break copying", async ({ page }) => {
  const events: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "info") events.push(message.text());
  });
  await page.route("https://umami.xingkaixin.me/script.js", (route) =>
    route.fulfill({
      contentType: "application/javascript",
      body: `window.umami = { track: async (name) => { console.info(name); throw new Error("Unavailable"); } };`,
    }),
  );
  await page.goto("/guides/export-codex-session/");
  await page.evaluate(() => {
    navigator.clipboard.writeText = async () => { throw new Error("Denied"); };
  });
  const block = page.locator(".guide-code").first();
  await block.getByRole("button", { name: "Copy", exact: true }).click();
  await expect(block.getByRole("status")).toContainText("Copy failed");
  expect(events).toEqual([]);
  await page.evaluate(() => {
    navigator.clipboard.writeText = async () => {};
  });
  await block.getByRole("button", { name: "Copy", exact: true }).click();
  await expect(block.getByRole("status")).toHaveText("Copied");
  expect(events).toEqual(["guide-copy"]);
});
