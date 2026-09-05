import { defineConfig, devices } from "@playwright/test";

const port = process.env.CHAT_FRAMES_PORT ?? "3011";
const baseURL = `http://localhost:${port}`;

export default defineConfig({
  testDir: "./tests/chat-frames",
  testMatch: "**/*-visual.spec.ts",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  outputDir: "test-results/chat-frames",
  reporter: [
    ["list"],
    ["html", { outputFolder: "playwright-report/chat-frames", open: "never" }],
    ["json", { outputFile: "test-output/chat-frames/summary.json" }],
  ],
  snapshotPathTemplate: "{testDir}/__screenshots__/{projectName}/{arg}{ext}",
  expect: {
    toHaveScreenshot: {
      animations: "disabled",
      caret: "hide",
      maxDiffPixelRatio: 0.005,
    },
  },
  use: {
    baseURL,
    locale: "en-US",
    timezoneId: "UTC",
    colorScheme: "light",
    deviceScaleFactor: 1,
    viewport: { width: 375, height: 812 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  webServer: {
    command: `bun run dev -- --hostname 127.0.0.1 --port ${port}`,
    url: `${baseURL}/chat-frames`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
  projects: [
    {
      name: "chat-chromium",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "chat-webkit",
      use: { ...devices["Desktop Safari"] },
    },
    {
      name: "chat-firefox",
      use: { ...devices["Desktop Firefox"] },
    },
  ],
});
