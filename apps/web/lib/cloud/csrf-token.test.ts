import { describe, expect, it } from "vitest";

import { createCloudCsrfTokenOwner } from "./csrf-token";

const token = "a".repeat(32);

describe("createCloudCsrfTokenOwner", () => {
  it("requires an in-memory token before unsafe requests", () => {
    const owner = createCloudCsrfTokenOwner();

    expect(() => owner.prepare(new Request("https://cloud.example.com/api/v1/auths/logout", { method: "POST" })))
      .toThrowError();
  });

  it("injects the current token only into unsafe credentialed requests", () => {
    const owner = createCloudCsrfTokenOwner();
    owner.replace(token);

    const post = owner.prepare(new Request("https://cloud.example.com/api/v1/auths/logout", { method: "POST" }));
    const get = owner.prepare(new Request("https://cloud.example.com/api/v1/auths/me"));

    expect(post.credentials).toBe("include");
    expect(post.headers.get("X-CSRFToken")).toBe(token);
    expect(get.credentials).toBe("include");
    expect(get.headers.has("X-CSRFToken")).toBe(false);
  });

  it("replaces and clears the value without exposing it as state", () => {
    const owner = createCloudCsrfTokenOwner();
    const replacement = "b".repeat(64);

    expect(owner.has()).toBe(false);
    owner.replace(token);
    expect(owner.has()).toBe(true);
    owner.replace(replacement);
    expect(owner.prepare(new Request("https://cloud.example.com/api/v1/auths/logout", { method: "POST" }))
      .headers.get("X-CSRFToken")).toBe(replacement);
    owner.clear();
    expect(owner.has()).toBe(false);
  });
});
