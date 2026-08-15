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

  it("composes Query and session providers and settles unauthorized restoration", async () => {
    vi.stubEnv("NEXT_PUBLIC_CLOUD_API_URL", "https://cloud.example.com");
    vi.stubEnv("NEXT_PUBLIC_WAITLIST_ENABLED", "true");
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const request = input instanceof Request ? input : new Request(input);
        if (request.url.endsWith("/csrf")) return new Response(null, { status: 204 });
        return Response.json(
          { status: "error", message: "Unauthorized", data: { code: "unauthorized" } },
          { status: 401 },
        );
      }),
    );

    render(
      <AppProviders>
        <SessionProbe />
      </AppProviders>,
    );

    expect(await screen.findByText("signed-out")).toBeTruthy();
  });

  it("does not restore the shared session when the waitlist is disabled", async () => {
    vi.stubEnv("NEXT_PUBLIC_CLOUD_API_URL", "https://cloud.example.com");
    vi.stubEnv("NEXT_PUBLIC_WAITLIST_ENABLED", "false");
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    render(
      <AppProviders>
        <SessionProbe />
      </AppProviders>,
    );

    expect(await screen.findByText("signed-out")).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
