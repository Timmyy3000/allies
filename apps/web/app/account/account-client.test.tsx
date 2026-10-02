// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const audio = vi.hoisted(() => ({ play: vi.fn(), setEnabled: vi.fn(), setVolume: vi.fn() }));
vi.mock("cuelume", () => audio);

import type { AccountViewModel, AvatarViewModel } from "@allies/cloud-client";

const navigation = vi.hoisted(() => ({ replace: vi.fn(), push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => navigation }));
const sessionMock = vi.hoisted(() => ({ useSession: vi.fn() }));
const avatarUploadMock = vi.hoisted(() => ({ uploadAvatar: vi.fn() }));
vi.mock("../../lib/session/session-context", () => sessionMock);
vi.mock("../../lib/account/avatar-upload", () => avatarUploadMock);
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: ReactNode }) => (
    <a href={href} {...props}>{children}</a>
  ),
}));

import { AVATAR_READ_QUERY_KEY, CURRENT_ACCOUNT_QUERY_KEY } from "../../lib/account/account-query";
import { AccountClient } from "./account-client";
import { InteractionSoundsProvider } from "../../lib/interaction-sounds";

const account: AccountViewModel = {
  userId: "usr_example",
  displayName: "Ada Lovelace",
  avatarUrl: null,
  session: { id: "ses_example", expiresAt: "2099-01-01T00:00:00Z" },
  workspace: {
    id: "wsp_example",
    name: "Ada's Workspace",
    role: "owner",
    capabilities: ["profile.read", "profile.write", "avatar.read", "avatar.write"],
  },
};

const avatar: AvatarViewModel = {
  assetId: "avt_example",
  url: "https://media.example/avatar",
  expiresAt: new Date(Date.now() + 60_000).toISOString(),
};

const sally = { id: "00000000-0000-4000-8000-00000000000a", name: "Sally", job: "Cooking", label: "Food errands", showLabel: true, appearance: { catalogVersion: "v1", key: "boxy:ff5800" } };
const mo = { id: "00000000-0000-4000-8000-00000000000b", name: "Mo", job: "Money and bills", appearance: { catalogVersion: "v1", key: "rolly:fd304f" } };
const gmail = {
  connectionId: "gmc_example",
  accountEmail: "ada@example.com",
  scopes: [],
  connectedAt: "2026-09-20T10:00:00Z",
  allyGrants: [{ allyId: sally.id, level: "read", grantGeneration: 1, updatedAt: "2026-09-20T10:00:00Z" }],
};

function operationRunner<T>(operation: (signal?: AbortSignal) => Promise<T>) {
  return operation();
}

function setupSession(overrides: Record<string, unknown> = {}) {
  const client = {
    getCurrentAccount: vi.fn(async () => account),
    getAvatarRead: vi.fn(async () => avatar),
    listAllies: vi.fn(async () => [sally, mo]),
    getIntegrationConnection: vi.fn(async (_workspace: string, _provider: string): Promise<unknown> => null),
    setIntegrationGrant: vi.fn(async (_workspace: string, _provider: string, allyId: string, level: string) => ({ allyId, level, grantGeneration: 2, updatedAt: "2026-09-21T10:00:00Z" })),
    disconnectIntegration: vi.fn(async () => undefined),
    listSafeInputs: vi.fn(async (): Promise<unknown[]> => []),
    deleteAvatar: vi.fn(async () => undefined),
    getWorkspace: vi.fn(async () => account.workspace),
  };
  const session = {
    state: { status: "signed-in" },
    restore: vi.fn(async () => undefined),
    logout: vi.fn(async () => ({ status: "signed-out", serverConfirmed: true })),
    client,
    runCloudOperation: vi.fn(operationRunner),
    ...overrides,
  };
  sessionMock.useSession.mockReturnValue(session);
  return { client, session };
}

function renderAccount(seed = account) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  queryClient.setQueryData(CURRENT_ACCOUNT_QUERY_KEY, seed);
  const result = render(
    <QueryClientProvider client={queryClient}>
      <InteractionSoundsProvider><AccountClient /></InteractionSoundsProvider>
    </QueryClientProvider>,
  );
  return { ...result, queryClient };
}

afterEach(cleanup);
beforeEach(() => {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
  vi.clearAllMocks();
  window.localStorage.clear();
  delete document.documentElement.dataset.theme;
  sessionMock.useSession.mockReset();
  avatarUploadMock.uploadAvatar.mockReset();
});

describe("AccountClient", () => {
  it("renders the Cloud-owned profile and Workspace without a redundant Workspace request", () => {
    const { client } = setupSession();
    renderAccount();

    expect(screen.getByRole("heading", { name: "Settings" })).toBeTruthy();



    expect(client.getWorkspace).not.toHaveBeenCalled();
  });

  it("keeps signed-out controls out of the unknown/restoring state", () => {
    const restore = vi.fn(async () => undefined);
    setupSession({ state: { status: "unknown" }, restore });
    renderAccount();

    expect(screen.getByRole("status", { name: "Restoring your account" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: /sign in/i })).toBeNull();
    expect(restore).toHaveBeenCalledOnce();
  });

  it("redirects signed-out visitors without displaying private data or sign-in controls", async () => {
    setupSession({ state: { status: "signed-out" } });
    renderAccount();
    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/"));
    expect(screen.queryByText("Ada Lovelace")).toBeNull();
    expect(screen.queryByRole("link", { name: /sign in/i })).toBeNull();
  });
  it("shows the first name only and no editable name field", () => {
    setupSession();
    renderAccount();
    expect(screen.getByRole("heading", { name: "Ada" })).toBeTruthy();
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("persists the interaction sound preference beside notification settings", () => {
    setupSession();
    renderAccount();
    const toggle = screen.getByRole("switch", { name: "Interaction sounds" });
    expect(toggle.getAttribute("aria-checked")).toBe("false");
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-checked")).toBe("true");
    expect(window.localStorage.getItem("allies:interaction-sounds:v1")).toBe("on");
    expect(audio.play).toHaveBeenCalledExactlyOnceWith("toggle", { emphasis: "subtle" });
  });

  it("keeps a failed photo and retries the full upload", async () => {
    const { client } = setupSession();
    const selected = new File(["avatar"], "profile.png", { type: "image/png" });
    avatarUploadMock.uploadAvatar
      .mockRejectedValueOnce({ kind: "timeout" })
      .mockResolvedValueOnce(avatar);
    const { queryClient } = renderAccount({ ...account, avatarUrl: "https://media.example/old" });
    queryClient.setQueryData(AVATAR_READ_QUERY_KEY, avatar);

    fireEvent.click(screen.getByRole("button", { name: "Change profile photo" }));
    fireEvent.change(screen.getByLabelText("Choose a profile photo"), { target: { files: [selected] } });

    expect((await screen.findByRole("alert")).textContent).toContain("couldn't save that photo");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(avatarUploadMock.uploadAvatar).toHaveBeenCalledTimes(2));
    expect(avatarUploadMock.uploadAvatar.mock.calls[1]?.[0]).toBe(selected);
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(client.getWorkspace).not.toHaveBeenCalled();
  });

  it.each([
    ["first upload", null],
    ["replacement", "https://media.example/old"],
  ])("refetches a usable avatar when %s completion has no URL", async (_name, previousUrl) => {
    const { client } = setupSession();
    const selected = new File(["avatar"], "profile.png", { type: "image/png" });
    const refreshedAccount = { ...account, avatarUrl: "https://media.example/avatar-asset" };
    const refreshedAvatar = { ...avatar, url: "https://media.example/new-signed" };
    client.getCurrentAccount.mockResolvedValue(refreshedAccount);
    if (previousUrl) {
      client.getAvatarRead
        .mockResolvedValueOnce({ ...avatar, url: previousUrl })
        .mockResolvedValue(refreshedAvatar);
    } else {
      client.getAvatarRead.mockResolvedValue(refreshedAvatar);
    }
    avatarUploadMock.uploadAvatar.mockResolvedValue({ assetId: "avt_example", url: null, expiresAt: null });
    const { queryClient, container } = renderAccount({ ...account, avatarUrl: previousUrl });
    if (previousUrl) queryClient.setQueryData(AVATAR_READ_QUERY_KEY, { ...avatar, url: previousUrl });
    if (previousUrl) await waitFor(() => expect(client.getAvatarRead).toHaveBeenCalledOnce());

    fireEvent.click(screen.getByRole("button", { name: /profile photo/ }));
    fireEvent.change(screen.getByLabelText("Choose a profile photo"), { target: { files: [selected] } });

    await waitFor(() => expect(queryClient.getQueryData<AvatarViewModel>(AVATAR_READ_QUERY_KEY)?.url)
      .toBe(refreshedAvatar.url));
    await waitFor(() => expect(container.querySelector("main img[src]")?.getAttribute("src")).toBe(refreshedAvatar.url));
  });

  it("lists Gmail with the Allies that use it and toggles access per Ally", async () => {
    const { client } = setupSession();
    client.getIntegrationConnection.mockImplementation(async (_workspace, provider) => (provider === "gmail" ? gmail : null));
    renderAccount();

    const row = await screen.findByRole("button", { name: /Gmail/ });
    expect(screen.getByRole("img", { name: "Used by Sally" })).toBeTruthy();
    fireEvent.click(row);

    expect(screen.getByText("Food errands")).toBeTruthy();
    expect(screen.getByText("Money and bills")).toBeTruthy();
    fireEvent.click(screen.getByRole("switch", { name: "Mo can use Gmail" }));
    await waitFor(() => expect(client.setIntegrationGrant).toHaveBeenCalledWith("wsp_example", "gmail", mo.id, "read", undefined));
    await waitFor(() => expect((screen.getByRole("switch", { name: "Mo can use Gmail" }) as HTMLInputElement).checked).toBe(true));
  });

  it("names the Allies losing access before disconnecting Gmail", async () => {
    const { client } = setupSession();
    client.getIntegrationConnection.mockImplementation(async (_workspace, provider) => (provider === "gmail" ? gmail : null));
    renderAccount();

    fireEvent.click(await screen.findByRole("button", { name: /Gmail/ }));
    fireEvent.click(screen.getByRole("button", { name: "Disconnect Gmail" }));
    expect(screen.getByText("Sally will stop using it straight away.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Disconnect" }));

    await waitFor(() => expect(client.disconnectIntegration).toHaveBeenCalledOnce());
    expect(await screen.findByRole("button", { name: "Connect Gmail" })).toBeTruthy();
  });

  it("lists Calendar beside Gmail and grants it write access per Ally", async () => {
    const { client } = setupSession();
    client.getIntegrationConnection.mockImplementation(async (_workspace, provider) => (
      provider === "gmail" ? gmail : { ...gmail, accountEmail: "cal@example.com", allyGrants: [{ allyId: mo.id, level: "write", grantGeneration: 1, updatedAt: "2026-09-20T10:00:00Z" }] }
    ));
    renderAccount();

    expect(await screen.findByText("2 connected")).toBeTruthy();
    fireEvent.click(await screen.findByRole("button", { name: /Calendar/ }));
    fireEvent.click(screen.getByRole("switch", { name: "Sally can use Calendar" }));
    await waitFor(() => expect(client.setIntegrationGrant).toHaveBeenCalledWith("wsp_example", "calendar", sally.id, "write", undefined));
    expect(client.disconnectIntegration).not.toHaveBeenCalled();
  });

  it("lists saved Safe inputs and hides the section when there are none", async () => {
    const first = setupSession();
    first.client.listSafeInputs.mockResolvedValue([{ id: "si_1", name: "Netflix", website: "netflix.com", allyIds: [mo.id], updatedAt: "2026-09-20T10:00:00Z" }]);
    renderAccount();
    expect(await screen.findByText("netflix.com")).toBeTruthy();
    expect(screen.getByText("1 saved")).toBeTruthy();
    expect(await screen.findByRole("img", { name: "Used by Mo" })).toBeTruthy();
    cleanup();

    setupSession();
    renderAccount();
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Safe inputs" })).toBeNull());
  });

  it("saves the picked theme and applies it", () => {
    setupSession();
    renderAccount();

    fireEvent.click(screen.getByRole("button", { name: /Appearance/ }));
    fireEvent.click(screen.getByRole("radio", { name: "Dark" }));

    expect(window.localStorage.getItem("allies.theme")).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(screen.getByRole("button", { name: /Appearance/ }).textContent).toContain("Dark");
  });

  it("preserves unconfirmed server logout on the landing page", async () => {
    const logout = vi.fn(async () => ({ status: "signed-out" as const, serverConfirmed: false }));
    setupSession({ logout });
    renderAccount();

    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));

    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/?signout=unconfirmed"));
    expect(logout).toHaveBeenCalledOnce();
  });

  it("returns standalone logout to the app route", async () => {
    window.matchMedia = vi.fn().mockReturnValue({ matches: true });
    setupSession();
    renderAccount();

    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));

    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/app"));
  });
});
