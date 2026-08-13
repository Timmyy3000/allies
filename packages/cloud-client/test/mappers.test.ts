import { describe, expect, it } from "vitest";

import { toAccountViewModel } from "../src/mappers/account";

describe("toAccountViewModel", () => {
  const account = {
    user: { id: "usr_example" },
    profile: { display_name: "Example User", avatar_url: null },
    session: { id: "ses_example", expires_at: "2026-08-13T12:00:00Z" },
    workspace: {
      id: "wsp_example",
      name: "Personal Workspace",
      role: "owner",
      capabilities: ["workspace:manage"],
    },
  };

  it("maps the wire account into Interface vocabulary", () => {
    expect(toAccountViewModel(account)).toEqual({
      userId: "usr_example",
      displayName: "Example User",
      avatarUrl: null,
      session: { id: "ses_example", expiresAt: "2026-08-13T12:00:00Z" },
      workspace: {
        id: "wsp_example",
        name: "Personal Workspace",
        role: "owner",
        capabilities: ["workspace:manage"],
      },
    });
  });

  it("allows additive wire fields but rejects consumed-field drift", () => {
    expect(toAccountViewModel({ ...account, future: true })).toMatchObject({ userId: "usr_example" });
    expect(() => toAccountViewModel({ ...account, session: { ...account.session, expires_at: "tomorrow" } })).toThrow();
  });
});
