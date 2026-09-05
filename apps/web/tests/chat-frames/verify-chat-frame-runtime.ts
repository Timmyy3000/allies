import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";

const require = createRequire(import.meta.url);
type BrowserRecord = { name: string; browserVersion?: string; revision?: string };

function fail(message: string): never {
  throw new Error(`[chat-frame-runtime] ${message}`);
}

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) fail(message);
}

function main() {
  if (process.env.CI === "true") {
    assert(process.versions.bun === "1.2.20", `Bun 1.2.20 is required in CI (found ${process.versions.bun ?? "unknown"})`);
  } else if (process.versions.bun !== "1.2.20") {
    console.warn(`[chat-frame-runtime] local Bun ${process.versions.bun ?? "unknown"}; CI baseline generation requires Bun 1.2.20`);
  }
  const playwrightPackage = require.resolve("playwright/package.json");
  const playwrightVersion = (JSON.parse(readFileSync(playwrightPackage, "utf8")) as { version: string }).version;
  assert(playwrightVersion === "1.62.1", `Playwright 1.62.1 is required (found ${playwrightVersion})`);
  const browsersPath = resolve(dirname(require.resolve("playwright-core/package.json")), "browsers.json");
  const browsers = (JSON.parse(readFileSync(browsersPath, "utf8")) as { browsers: BrowserRecord[] }).browsers;
  const expected: Record<string, { browserVersion: string; revision: string }> = {
    chromium: { browserVersion: "151.0.7922.34", revision: "1234" },
    webkit: { browserVersion: "26.5", revision: "2336" },
    firefox: { browserVersion: "153.0", revision: "1538" },
  };
  for (const [name, fingerprint] of Object.entries(expected)) {
    const record = browsers.find((candidate) => candidate.name === name);
    assert(record, `${name} browser record is missing`);
    assert(record.browserVersion === fingerprint.browserVersion, `${name} browser version drifted`);
    assert(record.revision === fingerprint.revision, `${name} browser revision drifted`);
  }
  console.log(`[chat-frame-runtime] Bun ${process.versions.bun}, Playwright ${playwrightVersion}, Chromium ${expected.chromium.browserVersion}/${expected.chromium.revision}, WebKit ${expected.webkit.browserVersion}/${expected.webkit.revision}, Firefox ${expected.firefox.browserVersion}/${expected.firefox.revision}`);
}

try {
  main();
} catch (error) {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
}
