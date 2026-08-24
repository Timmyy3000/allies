// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useSession } from "../lib/session/session-context";
import AppProviders from "./providers";

function SessionProbe() {
  return <span>{useSession().state.status}</span>;
}

describe("AppProviders", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("creates one shared provider lifetime and does not restore public routes", async () => {
    vi.stubEnv("NEXT_PUBLIC_CLOUD_API_URL", "https://cloud.example.com");
    vi.stubEnv("NEXT_PUBLIC_WAITLIST_ENABLED", "true");
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    render(
      <AppProviders>
        <SessionProbe />
      </AppProviders>,
    );

    expect(await screen.findByText("unknown")).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("does not depend on an Interface-origin CSRF cookie", async () => {
    vi.stubEnv("NEXT_PUBLIC_CLOUD_API_URL", "https://cloud.example.com");
    vi.stubEnv("NEXT_PUBLIC_WAITLIST_ENABLED", "false");
    document.cookie = "csrf_token=stale-interface-cookie; path=/";
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    render(
      <AppProviders>
        <SessionProbe />
      </AppProviders>,
    );

    expect(await screen.findByText("unknown")).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
