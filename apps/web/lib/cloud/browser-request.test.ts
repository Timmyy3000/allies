// @vitest-environment jsdom

import { describe, expect, it } from "vitest";

import { prepareBrowserCloudRequest, readCookie } from "./browser-request";

describe("browser Cloud request preparation", () => {
  it("reads the exact CSRF cookie", () => {
    expect(readCookie("other=a; csrf_token=csrf%20value", "csrf_token")).toBe("csrf value");
    expect(readCookie("csrf_token=%E0%A4%A", "csrf_token")).toBeNull();
  });

  it("adds credentials and CSRF only to unsafe requests", () => {
    document.cookie = "csrf_token=csrf-value; path=/";
    const post = prepareBrowserCloudRequest(new Request("https://cloud.example.com/action", { method: "POST" }));
    const get = prepareBrowserCloudRequest(new Request("https://cloud.example.com/read"));

    expect(post.credentials).toBe("include");
    expect(post.headers.get("X-CSRFToken")).toBe("csrf-value");
    expect(get.headers.has("X-CSRFToken")).toBe(false);
  });

  it("leaves waitlist CSRF to the same-origin facade", () => {
    document.cookie = "csrftoken=waitlist-csrf; path=/";

    const request = prepareBrowserCloudRequest(
      new Request("https://cloud.example.com/api/v1/waitlist/draft", { method: "POST" }),
    );

    expect(new URL(request.url).origin).toBe(window.location.origin);
    expect(new URL(request.url).pathname).toBe("/api/v1/waitlist/draft");
    expect(request.credentials).toBe("include");
    expect(request.headers.has("X-CSRFToken")).toBe(false);
    expect(request.headers.has("Origin")).toBe(false);
  });

  it("keeps auth requests on their existing CSRF cookie branch", () => {
    document.cookie = "csrf_token=auth-csrf; path=/";
    document.cookie = "csrftoken=waitlist-csrf; path=/";

    const request = prepareBrowserCloudRequest(
      new Request("https://cloud.example.com/api/v1/auths/logout", { method: "POST" }),
    );

    expect(request.url).toBe("https://cloud.example.com/api/v1/auths/logout");
    expect(request.headers.get("X-CSRFToken")).toBe("auth-csrf");
  });
});
