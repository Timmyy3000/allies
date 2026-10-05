import { defineConfig } from "@playwright/test";

const port = process.env.PW_PORT ?? "3010";
const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: "./app/(onboarding)/_tests",
  fullyParallel: false,
  use: {
    baseURL,
    viewport: { width: 390, height: 844 },
  },
  webServer: {
    command: `bun run dev -- --hostname 127.0.0.1 --port ${port}`,
    url: `${baseURL}/onboarding`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
