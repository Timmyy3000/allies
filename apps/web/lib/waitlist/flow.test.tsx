// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  CloudClient,
  WaitlistSnapshotViewModel,
} from "@allies/cloud-client";

import {
  OnboardingStateProvider,
  useOnboardingStore,
} from "../../app/(onboarding)/_store/onboarding-store";
import { useWaitlistFlow, WaitlistFlowProvider } from "./flow";

const useCloudClientMock = vi.hoisted(() => vi.fn());

vi.mock("../session/session-context", () => ({
  useCloudClient: useCloudClientMock,
}));

const ACK = {
  operation: "waitlist_test",
  resultLifecycle: "ready_for_greeting",
  resultRevision: 2,
};

const baseSnapshot: WaitlistSnapshotViewModel = {
  id: "draft_test",
  lifecycle: "ready_for_greeting",
  revision: 1,
  configuration: {
    name: "Nova",
    appearanceCatalogVersion: "v1",
    appearanceKey: "boxy:ff5800",
    job: "organize launch notes",
    personality: "Concise",
  },
  greeting: null,
  reply: null,
  join: null,
  timestamps: {
    createdAt: "2026-08-15T12:00:00Z",
    expiresAt: "2026-08-22T12:00:00Z",
    generatedAt: null,
    joinedAt: null,
    repliedAt: null,
    updatedAt: "2026-08-15T12:00:00Z",
  },
};

function makeSnapshot(overrides: Partial<WaitlistSnapshotViewModel> = {}): WaitlistSnapshotViewModel {
  return {
    ...baseSnapshot,
    ...overrides,
    configuration: { ...baseSnapshot.configuration, ...overrides.configuration },
    timestamps: { ...baseSnapshot.timestamps, ...overrides.timestamps },
  };
}

function createMockClient() {
  const methods = {
    getWaitlistSession: vi.fn(async () => undefined),
    getWaitlistDraft: vi.fn(async () => makeSnapshot()),
    createWaitlistDraft: vi.fn(async () => ACK),
    updateWaitlistConfiguration: vi.fn(async () => ACK),
    generateWaitlistGreeting: vi.fn(async () => ACK),
    recordWaitlistReply: vi.fn(async () => ACK),
    joinWaitlist: vi.fn(async () => ({ ...ACK, email: "person@example.com" })),
  };

  return { client: methods as unknown as CloudClient, methods };
}

type FlowValue = ReturnType<typeof useWaitlistFlow>;

function FlowProbe({
  capture,
  startActive,
}: {
  capture: (flow: FlowValue) => void;
  startActive: boolean;
}) {
  const flow = useWaitlistFlow();
  const step = useOnboardingStore((state) => state.step);
  const name = useOnboardingStore((state) => state.name);
  const goTo = useOnboardingStore((state) => state.goTo);
  const startedRef = useRef(false);

  useEffect(() => {
    if (startActive && !startedRef.current) {
      startedRef.current = true;
      goTo("name");
    }
  }, [goTo, startActive]);

  capture(flow);

  return (
    <div>
      <span data-testid="flow-status">{flow.status}</span>
      <span data-testid="flow-step">{step}</span>
      <span data-testid="flow-name">{name}</span>
      <span data-testid="flow-last-action">{flow.lastAction ?? ""}</span>
    </div>
  );
}

function renderFlow(
  client: CloudClient,
  options: { consentVersion?: string | null; startActive?: boolean } = {},
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 30_000 } },
  });
  let latestFlow: FlowValue | null = null;
  useCloudClientMock.mockReturnValue(client);

  render(
    <QueryClientProvider client={queryClient}>
      <OnboardingStateProvider>
        <WaitlistFlowProvider
          featureEnabled
          consentVersion={options.consentVersion === undefined ? "waitlist-v1" : options.consentVersion}
        >
          <FlowProbe
            startActive={options.startActive ?? true}
            capture={(flow) => {
              latestFlow = flow;
            }}
          />
        </WaitlistFlowProvider>
      </OnboardingStateProvider>
    </QueryClientProvider>,
  );

  return {
    queryClient,
    flow: () => {
      if (!latestFlow) throw new Error("The waitlist flow has not rendered yet.");
      return latestFlow;
    },
  };
}

async function waitForReady(): Promise<void> {
  await waitFor(() => expect(screen.getByTestId("flow-status").textContent).toBe("ready"));
}

const configurationPayload = {
  name: "Nova",
  appearance_catalog_version: "v1" as const,
  appearance_key: "boxy:ff5800",
  job: "organize launch notes",
  personality: "Concise",
};

describe("WaitlistFlowProvider", () => {
  afterEach(() => {
    cleanup();
    useCloudClientMock.mockReset();
  });

  it("rejects a second mutation while the first one is still in flight", async () => {
    const { client, methods } = createMockClient();
    let resolveUpdate: ((value: typeof ACK) => void) | undefined;
    methods.updateWaitlistConfiguration.mockImplementation(
      () => new Promise((resolve) => {
        resolveUpdate = resolve;
      }),
    );
    const rendered = renderFlow(client);
    await waitForReady();

    const first = rendered.flow().saveConfiguration(configurationPayload);
    await waitFor(() => expect(methods.updateWaitlistConfiguration).toHaveBeenCalledTimes(1));

    await expect(rendered.flow().saveConfiguration(configurationPayload)).rejects.toMatchObject({
      code: "operation_in_flight",
    });

    resolveUpdate?.(ACK);
    await first;
  });

  it("maps serialized configuration fields to the Cloud client input", async () => {
    const { client, methods } = createMockClient();
    const rendered = renderFlow(client);
    await waitForReady();

    await rendered.flow().saveConfiguration(configurationPayload);

    expect(methods.updateWaitlistConfiguration).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "Nova",
        appearanceCatalogVersion: "v1",
        appearanceKey: "boxy:ff5800",
        job: "organize launch notes",
        personality: "Concise",
      }),
    );
  });

  it("uses a server-authoritative refresh after a mutation while the query is still fresh", async () => {
    const { client, methods } = createMockClient();
    const rendered = renderFlow(client);
    await waitForReady();

    const updatedSnapshot = makeSnapshot({
      revision: 2,
      configuration: { ...baseSnapshot.configuration, job: "launch the updated notes" },
    });
    const readsBeforeMutation = methods.getWaitlistDraft.mock.calls.length;
    methods.getWaitlistDraft.mockResolvedValue(updatedSnapshot);

    await expect(rendered.flow().saveConfiguration(configurationPayload)).resolves.toMatchObject({
      revision: 2,
      configuration: { job: "launch the updated notes" },
    });

    expect(methods.getWaitlistDraft.mock.calls.length).toBeGreaterThan(readsBeforeMutation);
    expect(rendered.queryClient.getQueryData(["waitlist", "draft", "flow"])).toMatchObject({ revision: 2 });
  });

  it("cancels a pre-existing draft read before the post-mutation authoritative refresh", async () => {
    const { client, methods } = createMockClient();
    const rendered = renderFlow(client);
    await waitForReady();

    let resolveStaleRead: ((snapshot: WaitlistSnapshotViewModel) => void) | undefined;
    const staleRead = new Promise<WaitlistSnapshotViewModel>((resolve) => {
      resolveStaleRead = resolve;
    });
    const updatedSnapshot = makeSnapshot({ revision: 2 });
    methods.getWaitlistDraft.mockClear();
    methods.getWaitlistDraft.mockImplementationOnce(() => staleRead).mockResolvedValue(updatedSnapshot);

    const staleRefresh = rendered.flow().refreshDraft().catch(() => undefined);
    await waitFor(() => expect(methods.getWaitlistDraft).toHaveBeenCalledTimes(1));

    await expect(rendered.flow().saveConfiguration(configurationPayload)).resolves.toMatchObject({ revision: 2 });
    resolveStaleRead?.(makeSnapshot({ revision: 1 }));
    await staleRefresh;

    expect(methods.getWaitlistDraft).toHaveBeenCalledTimes(2);
  });

  it("does not let a greeting poll cancel a mutation's authoritative refresh", async () => {
    const { client, methods } = createMockClient();
    const pending = makeSnapshot({ lifecycle: "greeting_pending" });
    const updated = makeSnapshot({ revision: 2, lifecycle: "ready_for_greeting" });
    let readCount = 0;
    let resolvePollingRead: ((snapshot: WaitlistSnapshotViewModel) => void) | undefined;
    const pollingRead = new Promise<WaitlistSnapshotViewModel>((resolve) => {
      resolvePollingRead = resolve;
    });
    methods.getWaitlistDraft.mockImplementation(async () => {
      readCount += 1;
      if (readCount <= 2) return pending;
      if (readCount === 3) return pollingRead;
      return updated;
    });

    const rendered = renderFlow(client);
    await waitForReady();
    await waitFor(() => expect(methods.getWaitlistDraft).toHaveBeenCalledTimes(3));

    await expect(rendered.flow().saveConfiguration(configurationPayload)).resolves.toMatchObject({ revision: 2 });
    resolvePollingRead?.(pending);

    expect(methods.getWaitlistDraft).toHaveBeenCalledTimes(4);
  });

  it("starts a post-generation authoritative read when a same-key restore poll is already running", async () => {
    const { client, methods } = createMockClient();
    const pending = makeSnapshot({ lifecycle: "greeting_pending" });
    const ready = makeSnapshot({
      revision: 2,
      lifecycle: "greeting_ready",
      greeting: {
        text: "Hello from Nova.",
        policyVersion: "v1",
        generatedAt: "2026-08-15T12:00:01Z",
      },
    });
    let readCount = 0;
    let resolvePollingRead: ((snapshot: WaitlistSnapshotViewModel) => void) | undefined;
    const pollingRead = new Promise<WaitlistSnapshotViewModel>((resolve) => {
      resolvePollingRead = resolve;
    });
    methods.getWaitlistDraft.mockImplementation(async () => {
      readCount += 1;
      if (readCount <= 2) return pending;
      if (readCount === 3) return pollingRead;
      return ready;
    });

    const rendered = renderFlow(client);
    await waitForReady();
    await waitFor(() => expect(methods.getWaitlistDraft).toHaveBeenCalledTimes(3));

    const result = rendered.flow().generateGreeting("greeting-fingerprint");
    await expect(result).resolves.toMatchObject({ revision: 2, greeting: { text: "Hello from Nova." } });
    resolvePollingRead?.(pending);

    expect(methods.generateWaitlistGreeting).toHaveBeenCalledTimes(1);
    expect(methods.getWaitlistDraft).toHaveBeenCalledTimes(4);
  });

  it("retries a failed mutation with the same idempotency key", async () => {
    const { client, methods } = createMockClient();
    methods.updateWaitlistConfiguration
      .mockRejectedValueOnce({ kind: "network", code: "waitlist_request_failed" })
      .mockResolvedValue(ACK);
    const rendered = renderFlow(client);
    await waitForReady();

    await expect(rendered.flow().saveConfiguration(configurationPayload)).rejects.toMatchObject({
      kind: "network",
    });
    await waitFor(() => expect(screen.getByTestId("flow-last-action").textContent).toBe("configuration"));

    await rendered.flow().retry();

    expect(methods.updateWaitlistConfiguration).toHaveBeenCalledTimes(2);
    const calls = methods.updateWaitlistConfiguration.mock.calls as unknown as Array<
      [{ idempotencyKey: string }]
    >;
    const firstInput = calls[0]![0];
    const retryInput = calls[1]![0];
    expect(retryInput.idempotencyKey).toBe(firstInput.idempotencyKey);
  });

  it("polls a pending greeting to reconcile the authoritative snapshot", async () => {
    try {
      const { client, methods } = createMockClient();
      const rendered = renderFlow(client);
      await waitForReady();
      vi.useFakeTimers();

      const pending = makeSnapshot({ revision: 2, lifecycle: "greeting_pending" });
      const ready = makeSnapshot({
        revision: 3,
        lifecycle: "greeting_ready",
        greeting: {
          text: "Hello from Nova.",
          policyVersion: "v1",
          generatedAt: "2026-08-15T12:00:01Z",
        },
      });
      methods.getWaitlistDraft.mockResolvedValueOnce(pending).mockResolvedValueOnce(ready);

      const result = rendered.flow().generateGreeting("greeting-fingerprint");
      expect(methods.generateWaitlistGreeting).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(250);

      await expect(result).resolves.toMatchObject({ revision: 3, greeting: { text: "Hello from Nova." } });
      expect(methods.generateWaitlistGreeting).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("bounds pending greeting reconciliation and retries with a read instead of regenerating", async () => {
    try {
      const { client, methods } = createMockClient();
      const rendered = renderFlow(client);
      await waitForReady();
      vi.useFakeTimers();

      const pending = makeSnapshot({ revision: 2, lifecycle: "greeting_pending" });
      methods.getWaitlistDraft.mockResolvedValue(pending);

      const result = expect(rendered.flow().generateGreeting("greeting-fingerprint")).rejects.toMatchObject({
        code: "generation_outcome_unknown",
      });
      expect(methods.generateWaitlistGreeting).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(250 + 500 + 1_000 + 2_000);
      await result;

      const ready = makeSnapshot({
        revision: 3,
        lifecycle: "greeting_ready",
        greeting: {
          text: "Hello from Nova.",
          policyVersion: "v1",
          generatedAt: "2026-08-15T12:00:01Z",
        },
      });
      methods.getWaitlistDraft.mockResolvedValue(ready);
      await rendered.flow().retry();

      expect(methods.generateWaitlistGreeting).toHaveBeenCalledTimes(1);
      vi.useRealTimers();
      await waitFor(() => expect(screen.getByTestId("flow-last-action").textContent).toBe(""));
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps greeting recovery available when acknowledgement precedes the greeting snapshot", async () => {
    const { client, methods } = createMockClient();
    const rendered = renderFlow(client);
    await waitForReady();

    methods.getWaitlistDraft.mockResolvedValue(makeSnapshot());
    await expect(rendered.flow().generateGreeting("greeting-fingerprint")).rejects.toMatchObject({
      code: "generation_outcome_unknown",
    });
    await waitFor(() => expect(screen.getByTestId("flow-last-action").textContent).toBe("greeting"));

    methods.getWaitlistDraft.mockResolvedValue(
      makeSnapshot({
        lifecycle: "greeting_ready",
        greeting: {
          text: "Hello from Nova.",
          policyVersion: "v1",
          generatedAt: "2026-08-15T12:00:01Z",
        },
      }),
    );
    await rendered.flow().retry();

    expect(methods.generateWaitlistGreeting).toHaveBeenCalledTimes(2);
    const calls = methods.generateWaitlistGreeting.mock.calls as unknown as Array<
      [{ idempotencyKey: string }]
    >;
    expect(calls[1]![0].idempotencyKey).toBe(calls[0]![0].idempotencyKey);
    await waitFor(() => expect(screen.getByTestId("flow-last-action").textContent).toBe(""));
  });

  it("refreshes the snapshot after a stale-revision conflict", async () => {
    const { client, methods } = createMockClient();
    methods.recordWaitlistReply
      .mockRejectedValueOnce({ kind: "conflict", code: "stale_revision" })
      .mockResolvedValue(ACK);
    const rendered = renderFlow(client);
    await waitForReady();
    const draftReadsBeforeReply = methods.getWaitlistDraft.mock.calls.length;

    await expect(rendered.flow().recordReply("hello Nova")).rejects.toMatchObject({
      kind: "conflict",
    });

    await waitFor(() =>
      expect(methods.getWaitlistDraft.mock.calls.length).toBeGreaterThan(draftReadsBeforeReply),
    );
  });

  it("restores the onboarding store and returns to preview on refresh", async () => {
    const { client } = createMockClient();
    renderFlow(client, { startActive: false });

    await waitFor(() => expect(screen.getByTestId("flow-step").textContent).toBe("preview"));
    expect(screen.getByTestId("flow-name").textContent).toBe("Nova");
  });

  it("rejects joining without consent before calling Cloud", async () => {
    const { client, methods } = createMockClient();
    const rendered = renderFlow(client, { consentVersion: null });
    await waitForReady();

    await expect(rendered.flow().join("person@example.com")).rejects.toMatchObject({
      code: "consent_missing",
    });
    expect(methods.joinWaitlist).not.toHaveBeenCalled();
  });
});
