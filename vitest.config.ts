import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

const workspaceRoot = fileURLToPath(new URL(".", import.meta.url));
const sharedNodeModules = path.resolve(workspaceRoot, "node_modules");
const mobileNodeModules = path.resolve(workspaceRoot, "apps/mobile/node_modules");

function reactAliases(nodeModulesPath: string) {
  return [
    { find: "react-dom/client", replacement: path.resolve(nodeModulesPath, "react-dom/client.js") },
    { find: "react-dom/test-utils", replacement: path.resolve(nodeModulesPath, "react-dom/test-utils.js") },
    { find: "react/jsx-runtime", replacement: path.resolve(nodeModulesPath, "react/jsx-runtime.js") },
    { find: /^react-dom(\/.*)?$/, replacement: `${path.resolve(nodeModulesPath, "react-dom")}$1` },
    { find: /^react(\/.*)?$/, replacement: `${path.resolve(nodeModulesPath, "react")}$1` },
  ];
}

export default defineConfig({
  test: {
    projects: [
      {
        resolve: {
          alias: [...reactAliases(sharedNodeModules), { find: "@", replacement: path.resolve(workspaceRoot, "apps/web") }],
          dedupe: ["react", "react-dom"],
        },
        ssr: {
          noExternal: [
            "react",
            "react-dom",
            "@tanstack/react-query",
            "@testing-library/react",
            "motion",
            "framer-motion",
          ],
        },
        test: {
          name: "web",
          clearMocks: true,
          restoreMocks: true,
          include: ["apps/web/**/*.test.ts", "apps/web/**/*.test.tsx"],
        },
      },
      {
        root: path.resolve(workspaceRoot, "apps/mobile"),
        resolve: {
          alias: [
            ...reactAliases(mobileNodeModules),
            { find: "@/assets", replacement: path.resolve(workspaceRoot, "apps/mobile/assets") },
            { find: "@", replacement: path.resolve(workspaceRoot, "apps/mobile/src") },
          ],
          dedupe: ["react", "react-dom"],
        },
        ssr: {
          noExternal: ["react", "react-dom", "@tanstack/react-query", "@testing-library/react"],
        },
        test: {
          name: "mobile",
          clearMocks: true,
          restoreMocks: true,
          deps: {
            optimizer: {
              web: {
                enabled: true,
                include: ["react", "react-dom", "react-dom/client", "@tanstack/react-query", "@testing-library/react"],
              },
            },
          },
          include: ["*.test.ts", "src/**/*.test.ts", "src/**/*.test.tsx"],
        },
      },
      {
        test: {
          name: "packages",
          clearMocks: true,
          restoreMocks: true,
          include: ["packages/**/*.test.ts", "packages/**/*.test.tsx"],
        },
      },
    ],
  },
});
