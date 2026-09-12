// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AllyViewModel } from "@allies/cloud-client";
import { AllySettingsDetails } from "./settings-details";

vi.mock("@/components/ally-avatar", () => ({
  ALLY_SHAPES: ["ghosty"],
  AllyAvatar: ({ label }: { label: string }) => <div aria-label={label} />,
}));
const ally: AllyViewModel = {
  id: "ally", bindingId: "binding", operationId: "operation", name: "Mira",
  job: "Help with planning.\nKeep my calendar tidy.", personality: "Calm and curious",
  appearance: { catalogVersion: "v1", key: "ghosty:fd304f" }, provisioningState: "bound", retryable: false,
};
afterEach(cleanup);

describe("AllySettingsDetails", () => {
  it("keeps identity, job and personality read-only and does not invent label persistence", () => {
    render(<AllySettingsDetails ally={ally} />);
    expect(screen.getByRole("heading", { name: "Mira" })).toBeTruthy();
    expect(screen.getByText("Calm and curious")).toBeTruthy();
    expect(screen.getAllByRole("textbox")).toHaveLength(1);
    expect((screen.getByLabelText("Label") as HTMLInputElement).readOnly).toBe(true);
    expect(screen.queryByRole("button", { name: "Save label" })).toBeNull();
  });

  it("retains a failed edit and only announces success after persistence", async () => {
    let finish!: () => void;
    const onSave = vi.fn().mockRejectedValueOnce(new Error("offline"))
      .mockImplementationOnce(() => new Promise<void>((resolve) => { finish = resolve; }));
    render(<AllySettingsDetails ally={ally} label="Planning partner" onSaveLabel={onSave} />);
    fireEvent.change(screen.getByLabelText("Label"), { target: { value: "chief of staff" } });
    fireEvent.click(screen.getByRole("button", { name: "Save label" }));
    await screen.findByRole("alert");
    expect((screen.getByLabelText("Label") as HTMLInputElement).value).toBe("chief of staff");
    expect(screen.queryByText("Label saved")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Save label" }));
    expect((screen.getByRole("button", { name: "Saving…" }) as HTMLButtonElement).disabled).toBe(true);
    await act(async () => finish());
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Label saved"));
    expect(onSave).toHaveBeenCalledTimes(2);
    expect(onSave).toHaveBeenLastCalledWith("chief of staff");
  });
});
