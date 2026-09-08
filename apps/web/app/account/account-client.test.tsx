// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AccountViewModel, AvatarViewModel } from "@allies/cloud-client";

const navigation = vi.hoisted(() => ({ replace: vi.fn() }));
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

import { CURRENT_ACCOUNT_QUERY_KEY, AVATAR_READ_QUERY_KEY } from "../../lib/account/account-query";
import { AccountClient } from "./account-client";

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

function operationRunner<T>(operation: (signal?: AbortSignal) => Promise<T>) {
  return operation();
}

function setupSession(overrides: Record<string, unknown> = {}) {
  const client = {
    getCurrentAccount: vi.fn(async () => account),
    getAvatarRead: vi.fn(async () => avatar),
    updateProfile: vi.fn(async (displayName: string) => ({ displayName, avatarUrl: null })),
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
      <AccountClient />
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
  sessionMock.useSession.mockReset();
  avatarUploadMock.uploadAvatar.mockReset();
});

describe("AccountClient", () => {
  it("renders the Cloud-owned profile and Workspace without a redundant Workspace request", () => {
    const { client } = setupSession();
    renderAccount();

    expect(screen.getByRole("heading", { name: "Account" })).toBeTruthy();



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
  it("preserves the raw profile draft after a recoverable failure and updates Query after success", async () => {
    const { client } = setupSession();
    client.updateProfile
      .mockRejectedValueOnce({ kind: "server" })
      .mockImplementationOnce(async (displayName: string) => ({ displayName, avatarUrl: null }));
    const { queryClient } = renderAccount();
    const input = screen.getByRole("textbox", { name: "Display name" }) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "  Ada   Byron  " } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    const error = await screen.findByRole("alert");
    expect(error.textContent).toContain("couldn't save");
    expect(input.value).toBe("  Ada   Byron  ");

    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(queryClient.getQueryData<AccountViewModel>(CURRENT_ACCOUNT_QUERY_KEY)?.displayName)
      .toBe("Ada Byron"));
    expect(screen.getByText("Saved")).toBeTruthy();
  });

  it("retains the selected file on avatar failure and retries the complete lifecycle explicitly", async () => {
    const { client } = setupSession();
    const selected = new File(["avatar"], "profile.png", { type: "image/png" });
    avatarUploadMock.uploadAvatar
      .mockRejectedValueOnce({ kind: "timeout" })
      .mockResolvedValueOnce(avatar);
    const { queryClient } = renderAccount({ ...account, avatarUrl: "https://media.example/old" });
    queryClient.setQueryData(AVATAR_READ_QUERY_KEY, avatar);

    const input = screen.getByLabelText("Choose a profile avatar") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [selected] } });
    fireEvent.click(screen.getByRole("button", { name: "Upload avatar" }));

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(input.files?.[0]?.name).toBe("profile.png");

    fireEvent.click(screen.getByRole("button", { name: "Retry avatar upload" }));
    await waitFor(() => expect(avatarUploadMock.uploadAvatar).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("Avatar saved")).toBeTruthy();
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
    avatarUploadMock.uploadAvatar.mockResolvedValue({
      assetId: "avt_example",
      url: null,
      expiresAt: null,
    });
    const { queryClient } = renderAccount({ ...account, avatarUrl: previousUrl });
    if (previousUrl) queryClient.setQueryData(AVATAR_READ_QUERY_KEY, { ...avatar, url: previousUrl });

    if (previousUrl) await waitFor(() => expect(client.getAvatarRead).toHaveBeenCalledOnce());

    fireEvent.change(screen.getByLabelText("Choose a profile avatar"), { target: { files: [selected] } });
    fireEvent.click(screen.getByRole("button", { name: "Upload avatar" }));

    await waitFor(() => expect(queryClient.getQueryData<AvatarViewModel>(AVATAR_READ_QUERY_KEY)?.url)
      .toBe(refreshedAvatar.url));
    expect(screen.getByAltText("Profile avatar").getAttribute("src")).toBe(refreshedAvatar.url);
    expect(screen.getByText("Avatar saved")).toBeTruthy();
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
