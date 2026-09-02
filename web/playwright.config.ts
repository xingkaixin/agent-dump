import { defineConfig, devices } from "@playwright/test";

const port = process.env.PLAYWRIGHT_PORT ?? "4321";
const baseURL = `http://127.0.0.1:${port}`;

// Astro's static checks cannot execute hydrated controls, so this dev-only browser
// dependency guards the landing page's primary interactive paths.
export default defineConfig({
  testDir: "./tests/e2e",
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  // Locale journeys assert the process-wide system clipboard.
  workers: 1,
  reporter: "line",
  use: {
    baseURL,
    colorScheme: "light",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: {
    command: `pnpm exec astro preview --host 127.0.0.1 --port ${port}`,
    env: { ASTRO_PREVIEW_BACKGROUND: "0" },
    url: baseURL,
    reuseExistingServer: !process.env.CI,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
