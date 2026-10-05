import { defineConfig, devices } from "@playwright/test";

const port = process.env.HOME_SMOKE_PORT ?? "3012";
const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: "./tests/home-smoke",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  workers: 1,
  outputDir: "test-results/home-smoke",
  reporter: "list",
  use: {
    baseURL,
    trace: "retain-on-failure",
  },
  webServer: {
    command: `bun run start -- --hostname 127.0.0.1 --port ${port}`,
    url: `${baseURL}/home`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["iPhone 13"], browserName: "chromium" } },
    {
      name: "pwa-webkit",
      testMatch: "pwa-install.spec.ts",
      retries: process.env.CI ? 1 : 0,
      use: { ...devices["iPhone 13"], browserName: "webkit" },
    },
  ],
});
