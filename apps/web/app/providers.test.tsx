// @vitest-environment jsdom

import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useSession } from "../lib/session/session-context";
import AppProviders from "./providers";

function SessionProbe() {
  return <span>{useSession().state.status}</span>;
}

describe("AppProviders", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("composes Query and session providers and settles unauthorized restoration", async () => {
    process.env.NEXT_PUBLIC_CLOUD_API_URL = "https://cloud.example.com";
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
});
