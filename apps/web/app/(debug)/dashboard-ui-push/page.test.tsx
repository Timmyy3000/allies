import { afterEach, describe, expect, it, vi } from "vitest";
import DashboardUiPushDebugPage from "./page";

vi.mock("next/navigation", () => ({
  notFound: () => { throw new Error("NEXT_NOT_FOUND"); },
}));
vi.mock("./dashboard-ui-push-preview", () => ({ default: () => null }));

afterEach(() => vi.unstubAllEnvs());

describe("dashboard debug access", () => {
  it.each(["production", "preview", "staging"])("denies production builds labelled %s", (deployment) => {
    vi.stubEnv("NODE_ENV", "production");
    for (const name of ["VERCEL_ENV", "APP_ENV", "NEXT_PUBLIC_ENVIRONMENT", "NEXT_PUBLIC_APP_ENV"]) {
      vi.stubEnv(name, deployment);
    }
    expect(() => DashboardUiPushDebugPage()).toThrow("NEXT_NOT_FOUND");
  });

  it("allows local development", () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("VERCEL_ENV", "local");
    expect(DashboardUiPushDebugPage()).toBeTruthy();
  });
});
