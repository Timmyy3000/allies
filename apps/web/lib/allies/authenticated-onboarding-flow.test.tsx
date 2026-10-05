// @vitest-environment jsdom

import { act, cleanup, render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AllyViewModel } from "@allies/cloud-client";
import {
  AuthenticatedAllyFlowProvider,
  useCreationWake,
  useAuthenticatedAllyFlow,
} from "./authenticated-onboarding-flow";

const useSessionMock = vi.hoisted(() => vi.fn());
vi.mock("../session/session-context", () => ({ useSession: useSessionMock }));

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});
beforeEach(() => vi.clearAllMocks());

const configuration = {
  name: "Mira",
  appearance_catalog_version: "v1" as const,
  appearance_key: "ghosty:fd304f",
  job: "Help me plan",
  personality: "Calm and curious",
};

const ally = {
  id: "00000000-0000-4000-8000-000000000002",
  bindingId: "00000000-0000-4000-8000-000000000003",
  operationId: "00000000-0000-4000-8000-000000000004",
  name: "Mira",
  job: "Help me plan",
  personality: "Calm and curious",
  appearance: { catalogVersion: "v1", key: "ghosty:fd304f" },
  provisioningState: "pending",
  retryable: false,
} as AllyViewModel;

function Probe({ onFlow }: { onFlow: (flow: ReturnType<typeof useAuthenticatedAllyFlow>) => void }) {
  onFlow(useAuthenticatedAllyFlow());
  return null;
}

function WakeProbe({ onWake }: { onWake: (wake: ReturnType<typeof useCreationWake>) => void }) {
  onWake(useCreationWake());
  return null;
}

function renderFlow(overrides: {
  beginOnboarding?: ReturnType<typeof vi.fn>;
  createAlly?: ReturnType<typeof vi.fn>;
  requestWorkspaceRuntimeIntent?: ReturnType<typeof vi.fn>;
  creationWakeEnabled?: boolean;
  onCreated?: (created: AllyViewModel) => void;
} = {}) {
  const beginOnboarding = overrides.beginOnboarding ?? vi.fn(async () => ({
    attemptToken: "a".repeat(32),
    greeting: "Hello. What should we work on first?",
  }));
  const createAlly = overrides.createAlly ?? vi.fn(async () => ally);
  const requestWorkspaceRuntimeIntent = overrides.requestWorkspaceRuntimeIntent
    ?? vi.fn(async () => ({ status: "waking" as const }));
  useSessionMock.mockReturnValue({
    client: { beginOnboarding, createAlly, requestWorkspaceRuntimeIntent },
    runCloudOperation: vi.fn(async (
      operation: (signal?: AbortSignal) => Promise<unknown>,
      options?: { signal?: AbortSignal },
    ) => operation(options?.signal)),
  });

  let flow: ReturnType<typeof useAuthenticatedAllyFlow> | null = null;
  let wake: ReturnType<typeof useCreationWake> | null = null;
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <AuthenticatedAllyFlowProvider
        workspaceId="00000000-0000-4000-8000-000000000001"
        onCreated={overrides.onCreated ?? vi.fn()}
        creationWakeEnabled={overrides.creationWakeEnabled}
      >
        <Probe onFlow={(value) => { flow = value; }} />
        <WakeProbe onWake={(value) => { wake = value; }} />
      </AuthenticatedAllyFlowProvider>
    </QueryClientProvider>,
  );

  return { beginOnboarding, createAlly, requestWorkspaceRuntimeIntent, getFlow: () => flow!, getWake: () => wake };
}

describe("AuthenticatedAllyFlowProvider", () => {
  it("starts the official attempt and creates one Ally with a stable key on retry", async () => {
    const beginOnboarding = vi.fn(async () => ({
      attemptToken: "a".repeat(32),
      greeting: "Hello. What should we work on first?",
    }));
    const createAlly = vi
      .fn()
      .mockRejectedValueOnce(new Error("temporary failure"))
      .mockResolvedValue(ally);
    const onCreated = vi.fn();
    const { getFlow } = renderFlow({ beginOnboarding, createAlly, onCreated });

    await act(async () => {
      await getFlow().saveConfiguration(configuration);
    });
    expect(beginOnboarding).toHaveBeenCalledWith({
      name: "Mira",
      job: "Help me plan",
      personality: "Calm and curious",
      appearanceCatalogVersion: "v1",
      appearanceKey: "ghosty:fd304f",
    }, undefined);

    await act(async () => {
      await expect(getFlow().recordReply("Make tomorrow easier.")).rejects.toBeTruthy();
    });
    const firstKey = createAlly.mock.calls[0]?.[2];
    expect(firstKey).toEqual(expect.stringMatching(/^ally-create-/));
    expect(getFlow().snapshot.reply?.text).toBe("Make tomorrow easier.");

    await act(async () => {
      await getFlow().retry();
    });
    expect(createAlly).toHaveBeenCalledTimes(2);
    expect(createAlly.mock.calls[0]?.[1]).toMatchObject({
      onboardingAttempt: "a".repeat(32),
      reply: "Make tomorrow easier.",
    });
    expect(createAlly.mock.calls[1]?.[2]).toBe(firstKey);
    expect(onCreated).toHaveBeenCalledWith(ally, {
      greeting: "Hello. What should we work on first?",
      reply: "Make tomorrow easier.",
    });
  });

  it("rejects a reply before an onboarding attempt exists", async () => {
    const { getFlow } = renderFlow();

    await act(async () => {
      await expect(getFlow().recordReply("Hello.")).rejects.toMatchObject({
        code: "onboarding_configuration_missing",
      });
    });
  });

  it("keeps the creation wake disabled by default", async () => {
    const { getWake, requestWorkspaceRuntimeIntent } = renderFlow();

    await act(async () => {
      await getWake()?.requestCreationWake("Mira");
    });

    expect(requestWorkspaceRuntimeIntent).not.toHaveBeenCalled();
  });

  it("sends one content-free workspace intent with a UUID and no transient retry", async () => {
    const requestWorkspaceRuntimeIntent = vi.fn(async (...args: [string, string, AbortSignal?]) => {
      void args;
      return { status: "waking" as const };
    });
    const { getWake } = renderFlow({ creationWakeEnabled: true, requestWorkspaceRuntimeIntent });

    await act(async () => {
      await getWake()?.requestCreationWake("  Mira  ");
      await getWake()?.requestCreationWake("Mira again");
    });

    expect(requestWorkspaceRuntimeIntent).toHaveBeenCalledOnce();
    expect(requestWorkspaceRuntimeIntent.mock.calls[0]).toHaveLength(3);
    expect(requestWorkspaceRuntimeIntent.mock.calls[0]?.[0]).toMatch(/Z$/);
    expect(requestWorkspaceRuntimeIntent.mock.calls[0]?.[1]).toMatch(/^[0-9a-f-]{36}$/);
    expect(requestWorkspaceRuntimeIntent.mock.calls[0]?.[2]).toBeInstanceOf(AbortSignal);
  });

  it("aborts a stalled creation wake at its short timeout", async () => {
    vi.useFakeTimers();
    let signal: AbortSignal | undefined;
    const requestWorkspaceRuntimeIntent = vi.fn(async (...args: [string, string, AbortSignal?]) => {
      signal = args[2];
      return new Promise<{ status: "waking" }>(() => undefined);
    });
    const { getWake } = renderFlow({ creationWakeEnabled: true, requestWorkspaceRuntimeIntent });

    act(() => {
      void getWake()?.requestCreationWake("Mira");
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_500);
    });

    expect(signal?.aborted).toBe(true);
  });
});
