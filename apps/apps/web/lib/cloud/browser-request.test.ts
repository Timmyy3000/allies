// @vitest-environment jsdom

import { describe, expect, it } from "vitest";

import { createCloudCsrfTokenOwner } from "./csrf-token";
import { prepareBrowserCloudRequest } from "./browser-request";

describe("browser Cloud request preparation", () => {
  it("adds credentials and CSRF only to unsafe requests", () => {
    const owner = createCloudCsrfTokenOwner();
    owner.replace("c".repeat(32));
    const post = prepareBrowserCloudRequest(new Request("https://cloud.example.com/action", { method: "POST" }), owner);
    const get = prepareBrowserCloudRequest(new Request("https://cloud.example.com/read"), owner);

    expect(post.credentials).toBe("include");
    expect(post.headers.get("X-CSRFToken")).toBe("c".repeat(32));
    expect(get.headers.has("X-CSRFToken")).toBe(false);
  });

  it("sends public waitlist requests directly without cookies or CSRF", () => {
    const owner = createCloudCsrfTokenOwner();
    const request = prepareBrowserCloudRequest(
      new Request("https://cloud.example.com/api/v1/waitlist/entries", { method: "POST" }),
      owner,
    );

    expect(request.url).toBe("https://cloud.example.com/api/v1/waitlist/entries");
    expect(request.credentials).toBe("same-origin");
    expect(request.headers.has("X-CSRFToken")).toBe(false);
  });

  it("fails closed for an unsafe auth request without a token", () => {
    const owner = createCloudCsrfTokenOwner();

    expect(() => prepareBrowserCloudRequest(
      new Request("https://cloud.example.com/api/v1/auths/logout", { method: "POST" }),
      owner,
    )).toThrowError();
  });
});
