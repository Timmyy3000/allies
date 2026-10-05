import { describe, expect, it } from "vitest";
import { execFileSync } from "node:child_process";
import { ciScope } from "./ci-scope";

describe("CI scope", () => {
  it.each(["", "invalid-ref", "0000000000000000000000000000000000000000"])("runs full when comparison base is unavailable: %s", (base) => {
    const output = execFileSync("bun", ["scripts/ci-scope.ts"], {
      encoding: "utf8", env: { ...process.env, CI_BASE_SHA: base, CI_FULL: "false" },
      stdio: ["ignore", "pipe", "pipe"],
    });
    expect(output.trim().split(/\r?\n/)).toEqual(["web=true", "mobile=true", "browsers=true", "motion=true"]);
  });
  it("keeps docs-only changes in the always-run quality checks", () => {
    expect(ciScope(["docs/guide.md", "README.md"], false)).toEqual({
      web: false, mobile: false, browsers: false, motion: false,
    });
  });
  it("runs web smoke for web logic and cross-browser checks for UI", () => {
    expect(ciScope(["apps/web/lib/client.ts"], false)).toEqual({
      web: true, mobile: false, browsers: false, motion: false,
    });
    expect(ciScope(["apps/web/app/home/page.tsx"], false).browsers).toBe(true);
    expect(ciScope(["apps/web/next.config.ts"], false).browsers).toBe(true);
    expect(ciScope(["apps/web/components/ally-artwork.tsx"], false).motion).toBe(true);
  });
  it("runs mobile export for mobile-only changes", () => {
    expect(ciScope(["apps/mobile/app/index.tsx"], false)).toEqual({
      web: false, mobile: true, browsers: false, motion: false,
    });
  });
  it("runs cross-browser checks when only a browser spec changes", () => {
    expect(ciScope(["apps/web/tests/chat-frames/chat-frame-visual.spec.ts"], false).browsers).toBe(true);
  });
  it.each(["bun.lock", "packages/cloud-client/src/client.ts", ".github/workflows/ci.yml", "new-tool/config.json"])("fails broad for shared or unknown path %s", (path) => {
    expect(Object.values(ciScope([path], false)).every(Boolean)).toBe(true);
  });
  it("runs everything for release, scheduled and manual validation", () => {
    expect(Object.values(ciScope([], true)).every(Boolean)).toBe(true);
  });
  it("retains both scopes for mixed changes and animation coverage for adapters", () => {
    expect(ciScope(["apps/mobile/app/index.tsx", "apps/web/app/home/ally-avatar.tsx"], false)).toEqual({
      web: true, mobile: true, browsers: true, motion: true,
    });
  });
});
