import { readFileSync, readdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const debugDirectory = dirname(fileURLToPath(import.meta.url));

function runtimeFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = resolve(directory, entry.name);
    if (entry.isDirectory()) return runtimeFiles(path);
    return /\.(ts|tsx)$/.test(entry.name) && !entry.name.endsWith(".test.ts") && !entry.name.endsWith(".test.tsx") ? [path] : [];
  });
}

describe("debug chat-frame boundary", () => {
  it("contains no Cloud, transport, persistent storage, or production-controller dependencies", () => {
    for (const file of runtimeFiles(debugDirectory)) {
      const source = readFileSync(file, "utf8");
      expect(source, file).not.toMatch(/@allies\/cloud-client|@tanstack\/react-query|useSession|session-context|activity-stream|home-workspace|fetch\s*\(|localStorage|sessionStorage/);
      expect(source, file).not.toMatch(/public[\\/]debug|\.aphrodite[\\/]|\.fig\b/);
    }
  });

  it("imports shared visual code only through the explicit neutral boundary", () => {
    const renderer = readFileSync(resolve(debugDirectory, "debug-conversation-frame.tsx"), "utf8");
    expect(renderer).toContain("conversation-frame-primitives");
    expect(renderer).toContain("conversation-frame.module.css");
    expect(renderer).not.toContain("../../home/conversation-frame-model");
    expect(renderer).not.toContain("home-workspace");
  });

  it("keeps the guarded asset route fail closed", () => {
    const route = readFileSync(resolve(debugDirectory, "assets/[asset]/route.debug.ts"), "utf8");
    expect(route).toContain("canAccessChatFrames");
    expect(route).toContain("notFound");
  });
});
