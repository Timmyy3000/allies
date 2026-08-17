// @vitest-environment jsdom

import { act, cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CloudClient } from "@allies/cloud-client";
import { useWaitlistFlow, WaitlistFlowProvider } from "./flow";

const useCloudClientMock = vi.hoisted(() => vi.fn());
vi.mock("../session/session-context", () => ({ useCloudClient: useCloudClientMock }));

afterEach(cleanup);

describe("WaitlistFlowProvider", () => {
  it("creates once, keeps the reply local, and completes with email", async () => {
    const methods = {
      createWaitlistEntry: vi.fn(async () => ({ attemptToken: "token", greeting: "Hello." })),
      completeWaitlistEntry: vi.fn(async () => ({ email: "p****n@example.com" })),
    };
    useCloudClientMock.mockReturnValue(methods as unknown as CloudClient);
    let flow: ReturnType<typeof useWaitlistFlow> | null = null;
    function Probe() {
      flow = useWaitlistFlow();
      return null;
    }
    render(
      <WaitlistFlowProvider featureEnabled consentVersion="waitlist-v1">
        <Probe />
      </WaitlistFlowProvider>,
    );

    await act(async () => {
      await flow!.saveConfiguration({
        name: "Ari",
        appearance_catalog_version: "v1",
        appearance_key: "ghosty:fd304f",
        job: "Planning",
        personality: "Warm",
      });
    });
    await act(async () => {
      await flow!.recordReply("Help me plan.");
    });
    expect(methods.completeWaitlistEntry).not.toHaveBeenCalled();
    await act(async () => {
      await flow!.join("person@example.com");
    });

    expect(methods.createWaitlistEntry).toHaveBeenCalledTimes(1);
    expect(methods.completeWaitlistEntry).toHaveBeenCalledWith({
      attemptToken: "token",
      reply: "Help me plan.",
      email: "person@example.com",
      consentVersion: "waitlist-v1",
    });
    expect(flow!.snapshot.join?.email).toBe("p****n@example.com");
  });
});
