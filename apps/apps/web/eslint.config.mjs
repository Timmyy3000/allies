import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
  {
    files: ["app/home/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": ["error", {
        patterns: [{
          group: ["**/(debug)/**", "**/chat-frame-*"],
          message: "Production Home code cannot depend on the synthetic chat-frame harness.",
        }],
      }],
    },
  },
  {
    files: ["app/(debug)/chat-frames/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": ["error", {
        paths: [
          { name: "@allies/cloud-client", message: "Debug frames must not depend on Cloud DTOs or transport." },
          { name: "@tanstack/react-query", message: "Debug frames must stay outside the query cache." },
        ],
        patterns: [{
          group: [
            "**/home-workspace",
            "**/lib/session/**",
            "**/lib/allies/queries",
            "**/lib/allies/query-keys",
            "**/lib/allies/activity-stream",
          ],
          message: "Debug frames must not depend on production controllers or transport.",
        }],
      }],
      "no-restricted-globals": ["error",
        { name: "fetch", message: "Debug frames are local-only and cannot make network requests." },
        { name: "localStorage", message: "Debug frames cannot persist fixture state." },
        { name: "sessionStorage", message: "Debug frames cannot persist fixture state." },
      ],
    },
  },
]);

export default eslintConfig;
