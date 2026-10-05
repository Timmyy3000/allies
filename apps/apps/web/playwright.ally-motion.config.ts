import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/ally-motion',
  timeout: 30_000,
  use: { viewport: { width: 470, height: 470 }, trace: 'retain-on-failure' },
  projects: [
    { name: 'chromium', use: { browserName: 'chromium' } },
    { name: 'webkit', use: { browserName: 'webkit' } },
  ],
});
