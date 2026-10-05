import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  reporter: [["line"], ["json", { outputFile: "test-results/fnd009.json" }]],
  use: {
    baseURL: process.env.PW_BASE_URL ?? "http://127.0.0.1:3011",
    trace: "retain-on-failure",
    ...devices["Desktop Chrome"],
  },
  timeout: 120_000,
  expect: { timeout: 30_000 },
});
