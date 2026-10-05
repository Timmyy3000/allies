import { describe, expect, it, vi } from "vitest";

import { createCloudClient } from "../src/client";
import { toAllyViewModel } from "../src/mappers/allies";

const workspaceId = "00000000-0000-4000-8000-000000000001";
const allyId = "00000000-0000-4000-8000-000000000002";
const ally = {
  id: allyId,
  binding_id: "00000000-0000-4000-8000-000000000003",
  operation_id: "00000000-0000-4000-8000-000000000004",
  name: "Mira", job: "Help me organize my work", personality: "Calm and focused",
  appearance: { catalog_version: "v1", key: "sunrise" },
  provisioning_state: "bound", retryable: false,
};
const settings = { label: "chief of staff", showLabel: true, settingsRevision: 2 };

describe("ally label settings", () => {
  it("defaults legacy responses to hidden and rejects malformed current fields", () => {
    expect(toAllyViewModel(ally)).toMatchObject({ label: "", showLabel: false, settingsRevision: 0 });
    expect(() => toAllyViewModel({ ...ally, show_label: "false" })).toThrow();
    expect(() => toAllyViewModel({ ...ally, settings_revision: -1 })).toThrow();
  });

  it.each(["manager", "chief\nof staff", "social \u202emanager", " social manager", "a".repeat(79) + " b"])(
    "rejects malformed persisted labels (%s)", (label) => {
      expect(() => toAllyViewModel({ ...ally, label })).toThrow();
    },
  );

  it("counts Unicode code points consistently with persisted labels", async () => {
    const label = "𐐀".repeat(78) + " a";
    const fetch = vi.fn(async () => Response.json({ status: "success", message: "Saved", data: {
      ...ally, label, show_label: true, settings_revision: 3,
    } }));
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch });
    await expect(client.updateAllySettings(workspaceId, allyId, { ...settings, label }))
      .resolves.toMatchObject({ label });
    expect(toAllyViewModel({ ...ally, label }).label).toBe(label);
  });

  it("sends a scoped revision-bound PATCH and returns the persisted settings", async () => {
    const fetch = vi.fn(async (request: Request) => {
      expect(request.method).toBe("PATCH");
      expect(new URL(request.url).pathname).toBe(`/api/v1/workspaces/${workspaceId}/allies/${allyId}/settings`);
      expect(await request.json()).toEqual({ label: "chief of staff", show_label: true, settings_revision: 2 });
      return Response.json({ status: "success", message: "Saved", data: {
        ...ally, label: "chief of staff", show_label: true, settings_revision: 3,
      } });
    });
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch: fetch as typeof globalThis.fetch });
    await expect(client.updateAllySettings(workspaceId, allyId, {
      ...settings, label: " ".repeat(81) + settings.label,
    })).resolves.toMatchObject({
      id: allyId, label: "chief of staff", showLabel: true, settingsRevision: 3,
    });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("sends an optional appearance change with the settings PATCH", async () => {
    const fetch = vi.fn(async (request: Request) => {
      expect(await request.json()).toEqual({
        label: "chief of staff", show_label: true, settings_revision: 2,
        appearance: { catalog_version: "v1", key: "circle:0D92FD" },
      });
      return Response.json({ status: "success", message: "Saved", data: {
        ...ally, appearance: { catalog_version: "v1", key: "circle:0D92FD" },
        label: "chief of staff", show_label: true, settings_revision: 3,
      } });
    });
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch: fetch as typeof globalThis.fetch });
    await expect(client.updateAllySettings(workspaceId, allyId, {
      ...settings, appearance: { catalogVersion: "v1", key: "circle:0D92FD" },
    })).resolves.toMatchObject({ settingsRevision: 3 });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it.each([
    { ...settings, label: "" },
    { ...settings, label: "manager" },
    { ...settings, label: "chief\nof staff" },
    { ...settings, settingsRevision: -1 },
  ])("rejects invalid settings before network I/O", async (input) => {
    const fetch = vi.fn();
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch });
    await expect(client.updateAllySettings(workspaceId, allyId, input)).rejects.toMatchObject({ kind: "bad-request" });
    expect(fetch).not.toHaveBeenCalled();
  });

  it.each([409, 404, 503])("does not report a failed save as success or retry it (%s)", async (status) => {
    const fetch = vi.fn(async () => Response.json({ status: "error", data: { code: "settings_unavailable" } }, { status }));
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch });
    await expect(client.updateAllySettings(workspaceId, allyId, settings)).rejects.toMatchObject({ status });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("requires persisted settings in a successful save response", async () => {
    const fetch = vi.fn(async () => Response.json({ status: "success", message: "Saved", data: ally }));
    const client = createCloudClient({ baseUrl: "https://cloud.example.com", fetch });
    await expect(client.updateAllySettings(workspaceId, allyId, settings)).rejects.toMatchObject({ kind: "contract" });
  });
});
