// @vitest-environment jsdom

import { act, cleanup, render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AllyViewModel } from "@allies/cloud-client";
import {
  AuthenticatedAllyFlowProvider,
  useAuthenticatedAllyFlow,
} from "./authenticated-onboarding-flow";

const useSessionMock = vi.hoisted(() => vi.fn());
vi.mock("../session/session-context", () => ({ useSession: useSessionMock }));

afterEach(cleanup);
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

function renderFlow(overrides: {
  beginOnboarding?: ReturnType<typeof vi.fn>;
  createAlly?: ReturnType<typeof vi.fn>;
  onCreated?: (created: AllyViewModel) => void;
} = {}) {
  const beginOnboarding = overrides.beginOnboarding ?? vi.fn(async () => ({
    attemptToken: "a".repeat(32),
    greeting: "Hello. What should we work on first?",
  }));
  const createAlly = overrides.createAlly ?? vi.fn(async () => ally);
  useSessionMock.mockReturnValue({
    client: { beginOnboarding, createAlly },
    runCloudOperation: vi.fn(async (operation: (signal?: AbortSignal) => Promise<unknown>) => operation()),
  });

  let flow: ReturnType<typeof useAuthenticatedAllyFlow> | null = null;
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <AuthenticatedAllyFlowProvider
        workspaceId="00000000-0000-4000-8000-000000000001"
        onCreated={overrides.onCreated ?? vi.fn()}
      >
        <Probe onFlow={(value) => { flow = value; }} />
      </AuthenticatedAllyFlowProvider>
    </QueryClientProvider>,
  );

  return { beginOnboarding, createAlly, getFlow: () => flow! };
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
    expect(onCreated).toHaveBeenCalledWith(ally);
  });

  it("rejects a reply before an onboarding attempt exists", async () => {
    const { getFlow } = renderFlow();

    await act(async () => {
      await expect(getFlow().recordReply("Hello.")).rejects.toMatchObject({
        code: "onboarding_configuration_missing",
      });
    });
  });
});
