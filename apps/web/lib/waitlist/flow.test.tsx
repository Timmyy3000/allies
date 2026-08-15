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
    defaultOptions: { queries: { retry: false } },
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

  it("keeps greeting recovery available when acknowledgement precedes the greeting snapshot", async () => {
    const { client, methods } = createMockClient();
    const rendered = renderFlow(client);
    await waitForReady();

    methods.getWaitlistDraft.mockResolvedValue(makeSnapshot());
    await expect(rendered.flow().generateGreeting("greeting-fingerprint")).rejects.toMatchObject({
      code: "generation_outcome_unknown",
    });
    await waitFor(() => expect(screen.getByTestId("flow-last-action").textContent).toBe("greeting"));

    methods.getWaitlistDraft.mockResolvedValue(makeSnapshot({ lifecycle: "greeting_pending" }));
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
