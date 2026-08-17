// @vitest-environment jsdom

import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CloudClient } from "@allies/cloud-client";
import { useWaitlistFlow, WaitlistFlowProvider } from "./flow";

const useCloudClientMock = vi.hoisted(() => vi.fn());
const analyticsMock = vi.hoisted(() => ({
  captureWaitlistEvent: vi.fn(),
  identifyWaitlistSubscriber: vi.fn(),
}));
vi.mock("../session/session-context", () => ({ useCloudClient: useCloudClientMock }));
vi.mock("../analytics/waitlist", () => analyticsMock);

afterEach(cleanup);
beforeEach(() => vi.clearAllMocks());

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
    expect(analyticsMock.captureWaitlistEvent).toHaveBeenNthCalledWith(
      1,
      "waitlist_ally_created",
    );
    expect(analyticsMock.identifyWaitlistSubscriber).toHaveBeenCalledWith(
      expect.not.stringMatching("person@example.com"),
      "person@example.com",
    );
    expect(analyticsMock.captureWaitlistEvent).toHaveBeenNthCalledWith(
      2,
      "waitlist_joined",
    );
  });

  it("shares an in-flight create request", async () => {
    let resolveEntry: ((value: { attemptToken: string; greeting: string }) => void) | undefined;
    const methods = {
      createWaitlistEntry: vi.fn(
        () =>
          new Promise<{ attemptToken: string; greeting: string }>((resolve) => {
            resolveEntry = resolve;
          }),
      ),
      completeWaitlistEntry: vi.fn(),
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

    const payload = {
      name: "Ari",
      appearance_catalog_version: "v1",
      appearance_key: "ghosty:fd304f",
      job: "Planning",
      personality: "Warm",
    } as const;
    let first: Promise<unknown>;
    let second: Promise<unknown>;
    await act(async () => {
      first = flow!.saveConfiguration(payload);
      second = flow!.saveConfiguration(payload);
      expect(methods.createWaitlistEntry).toHaveBeenCalledTimes(1);
      resolveEntry?.({ attemptToken: "token", greeting: "Hello." });
      await Promise.all([first, second]);
    });
    expect(analyticsMock.captureWaitlistEvent).toHaveBeenCalledTimes(1);
    expect(analyticsMock.captureWaitlistEvent).toHaveBeenCalledWith(
      "waitlist_ally_created",
    );
  });
});
