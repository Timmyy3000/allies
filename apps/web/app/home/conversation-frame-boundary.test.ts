import { existsSync, readFileSync, statSync } from "node:fs";
import { dirname, extname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const homeDirectory = dirname(fileURLToPath(import.meta.url));
const repositoryRoot = resolve(homeDirectory, "../../../..");

function sourceImports(source: string): string[] {
  return [...source.matchAll(/(?:from\s+|import\s*\(\s*|require\s*\(\s*)(["'])([^"']+)\1/g)].map((match) => match[2]);
}

function resolveRelativeImport(fromFile: string, importPath: string): string | null {
  if (!importPath.startsWith(".")) return null;
  const base = resolve(dirname(fromFile), importPath);
  for (const suffix of ["", ".ts", ".tsx", ".js", ".jsx", ".css"] as const) {
    const candidate = `${base}${suffix}`;
    if (existsSync(candidate) && statSync(candidate).isFile()) return candidate;
  }
  for (const suffix of ["page.tsx", "route.ts", "index.ts", "index.tsx"] as const) {
    const candidate = resolve(base, suffix);
    if (existsSync(candidate) && statSync(candidate).isFile()) return candidate;
  }
  return null;
}

function productionGraph(): string[] {
  const roots = [
    resolve(homeDirectory, "page.tsx"),
    resolve(homeDirectory, "[allyId]/page.tsx"),
    resolve(homeDirectory, "new/page.tsx"),
    resolve(repositoryRoot, "apps/web/app/home/home-workspace.tsx"),
    resolve(repositoryRoot, "apps/web/app/home/conversation-frame-model.ts"),
    resolve(repositoryRoot, "apps/web/app/home/conversation-frame.tsx"),
  ];
  const visited = new Set<string>();
  const pending = [...roots];
  while (pending.length) {
    const file = pending.pop();
    if (!file || visited.has(file) || !existsSync(file)) continue;
    visited.add(file);
    const source = readFileSync(file, "utf8");
    for (const importPath of sourceImports(source)) {
      const imported = resolveRelativeImport(file, importPath);
      if (imported && extname(imported) !== ".css") pending.push(imported);
    }
  }
  return [...visited];
}

describe("production conversation frame boundary", () => {
  it("serves desktop shell imagery from existing local public assets", () => {
    const shell = readFileSync(resolve(homeDirectory, "_exact/dashboard-ui-push-exact.tsx"), "utf8");
    const sources = [...shell.matchAll(/src="([^"]+)"/g)].map((match) => match[1]);
    expect(sources.filter((source) => source.startsWith("/home/desktop-dashboard/"))).toHaveLength(7);
    for (const source of sources) {
      expect(source).toMatch(/^\/(?!\/)/);
      expect(existsSync(resolve(repositoryRoot, "apps/web/public", source.slice(1)))).toBe(true);
      if (source.startsWith("/home/desktop-dashboard/")) {
        const svg = readFileSync(resolve(repositoryRoot, "apps/web/public", source.slice(1)), "utf8");
        expect(svg.trim()).toMatch(/^<svg\b/);
        expect(svg).not.toMatch(/<script\b|<foreignObject\b|\bon\w+\s*=|(?:href|src)\s*=\s*["'](?!#)|url\(\s*["']?(?!#)/i);
      }
    }
  });

  it("does not reach synthetic debug modules, assets, or private source files", () => {
    const graph = productionGraph();
    expect(graph.length).toBeGreaterThan(3);
    expect(graph.some((file) => file.includes("(debug)"))).toBe(false);
    expect(graph.some((file) => /chat-frame-(fixtures|preview|debug|access)/.test(file))).toBe(false);
    expect(graph.some((file) => /home-(dashboard|route|mobile-preview|mobile-mock)\.[tj]sx?$/.test(file))).toBe(false);
    expect(graph.some((file) => /\.fig$|\.aphrodite[\\/]/.test(file))).toBe(false);
  });

  it("keeps the renderer prop surface production-only", () => {
    const source = readFileSync(resolve(repositoryRoot, "apps/web/app/home/conversation-frame.tsx"), "utf8");
    expect(source).toMatch(/model:\s*ProductionConversationFrameModel/);
    expect(source).not.toMatch(/DebugConversationFrameModel|DebugRichItem|ConversationFrameProps.*union/);
    expect(source).not.toMatch(/@allies\/cloud-client|@tanstack\/react-query|useSession|localStorage|fetch\s*\(/);
  });
});
