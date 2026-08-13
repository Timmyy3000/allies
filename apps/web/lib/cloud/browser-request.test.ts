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
});
