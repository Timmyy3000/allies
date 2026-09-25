import { expect, test, type Page } from "@playwright/test";
import { createHash } from "node:crypto";

const w = "00000000-0000-4000-8000-000000000001",
  a = "00000000-0000-4000-8000-000000000002",
  c = "00000000-0000-4000-8000-000000000003",
  m = "00000000-0000-4000-8000-000000000004",
  f = "00000000-0000-4000-8000-000000000005";
const csrf = "a".repeat(32),
  now = "2099-01-01T12:00:00Z";
function makePdfFixture() {
  const stream = "BT /F1 18 Tf 24 100 Td (PDF preview works) Tj ET";
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 240 160] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
    `<< /Length ${Buffer.byteLength(stream)} >>\nstream\n${stream}\nendstream`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ];
  let body = "%PDF-1.4\n";
  const offsets = objects.map((object, index) => {
    const offset = Buffer.byteLength(body);
    body += `${index + 1} 0 obj\n${object}\nendobj\n`;
    return offset;
  });
  const xref = Buffer.byteLength(body);
  body += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  body += offsets.map((offset) => `${String(offset).padStart(10, "0")} 00000 n \n`).join("");
  body += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(body);
}
const pdfBytes = makePdfFixture();
type PreviewKind = "text" | "pdf";
async function cloud(page: Page, fail = false, previewKind: PreviewKind = "text") {
  let reserved = false,
    state = "pending",
    preparation = "uploading",
    revision = 1,
    generation = 1,
    uploads = 0;
  const requests: string[] = [];
  const uploadBytes = previewKind === "pdf" ? pdfBytes : Buffer.from("hello");
  const fileName = previewKind === "pdf" ? "notes.pdf" : "notes.txt";
  const file = () => ({ id: f, name: fileName, size: uploadBytes.length, state });
  const message = () => ({
    id: m,
    sender: "user",
    content: "",
    sequence: 1,
    status: "queued",
    queue_state: "unclaimed",
    created_at: now,
    retryable: false,
    preparation,
    revision,
    files: preparation === "cancelled" ? [] : [file()],
  });
  await page.route("**/api/v1/**", async (route) => {
    const req = route.request(),
      path = new URL(req.url()).pathname;
    const headers = {
      "access-control-allow-origin":
        req.headers().origin ?? "http://127.0.0.1:3027",
      "access-control-allow-credentials": "true",
      "access-control-allow-headers":
        "content-type, idempotency-key, x-csrftoken",
      "access-control-allow-methods": "GET, POST, PUT, DELETE, OPTIONS",
      "access-control-expose-headers": "x-csrftoken",
    };
    const ok = (data: unknown, status = 200) =>
      route.fulfill({
        status,
        headers,
        json: { status: "success", message: "ok", data },
      });
    if (req.method() === "OPTIONS")
      return route.fulfill({ status: 204, headers });
    requests.push(`${req.method()} ${path}`);
    if (path.endsWith("/auths/me"))
      return ok({
        user: { id: "00000000-0000-4000-8000-000000000006" },
        profile: { display_name: "File tester", avatar_url: null },
        session: {
          id: "00000000-0000-4000-8000-000000000007",
          expires_at: now,
        },
        workspace: { id: w, name: "Files", role: "owner", capabilities: [] },
      });
    if (path.endsWith("/auths/csrf"))
      return route.fulfill({
        status: 204,
        headers: { ...headers, "x-csrftoken": csrf },
      });
    if (path.endsWith("/allies"))
      return ok({
        allies: [
          {
            id: a,
            binding_id: "00000000-0000-4000-8000-000000000008",
            operation_id: "00000000-0000-4000-8000-000000000009",
            name: "Ada",
            job: "Planning partner",
            personality: "Helpful",
            appearance: { catalog_version: "v1", key: "ghosty" },
            provisioning_state: "bound",
            retryable: false,
          },
        ],
      });
    if (
      path.endsWith(`/allies/${a}/conversation`) ||
      path.endsWith(`/conversations/${c}`)
    )
      return ok({
        id: c,
        ally_id: a,
        messages: reserved ? [message()] : [],
        assistant_replies: [],
        next_cursor: null,
      });
    if (path.endsWith("/activities"))
      return ok({
        conversation_id: c,
        activities: [],
        state: "completed",
        last_contiguous_sequence: 0,
      });
    if (path.endsWith("/approvals")) return ok({ approvals: [] });
    if (path.endsWith("/file-messages")) {
      expect(req.headers()["x-csrftoken"]).toBe(csrf);
      expect(req.headers()["idempotency-key"]).toBeTruthy();
      expect(req.postDataJSON().content).toBe("");
      expect(req.postDataJSON().files[0].sha256).toBe(createHash("sha256").update(uploadBytes).digest("hex"));
      const replayed = reserved;
      reserved = true;
      return ok(
        {
          message: {
            id: m,
            sequence: 1,
            status: "queued",
            preparation,
            revision,
          },
          files: [{ id: f, state, generation }],
          replayed,
        },
        202,
      );
    }
    if (path.endsWith(`/files/${f}/content`)) {
      expect(req.headers()["x-csrftoken"]).toBe(csrf);
      expect(req.postDataBuffer()).toEqual(uploadBytes);
      uploads++;
      state = fail && uploads === 1 ? "failed" : "ready";
      preparation =
        state === "failed" ? "failed" : revision > 1 ? "needs_retry" : "ready";
      return ok({ id: f, state: "validating", generation }, 202);
    }
    if (path.endsWith(`/files/${f}/retry`)) {
      generation++;
      revision++;
      state = "pending";
      return ok({ id: f, state, generation });
    }
    if (path.endsWith("/send-files")) {
      expect(req.postDataJSON()).toEqual({ revision });
      preparation = "ready";
      return ok({ id: m, status: "queued", preparation, revision: ++revision });
    }
    if (path.endsWith("/cancel-files")) {
      preparation = "cancelled";
      return ok({
        message: { id: m, status: "queued", preparation, revision: ++revision },
        draft: {
          id: m,
          content: "",
          files: [{ id: f, name: "notes.txt", state: "retained" }],
        },
      });
    }
    if (path.endsWith(`/files/${f}`))
      return ok({
        ...file(),
        type: previewKind === "pdf" ? "application/pdf" : "text/plain",
        preview_kind: previewKind,
        open_path: `/files/${f}`,
      });
    if (path.endsWith(`/files/${f}/preview`))
      return route.fulfill({
        headers,
        contentType: previewKind === "pdf" ? "application/octet-stream" : "text/plain",
        body: uploadBytes,
      });
    return route.fulfill({
      status: 404,
      headers,
      json: { status: "error", message: "Not found" },
    });
  });
  return { requests, uploads: () => uploads };
}
async function select(page: Page, previewKind: PreviewKind = "text") {
  await page.goto(`/home/${a}`);
  await page.getByRole("button", { name: "Add attachment" }).click();
  await page.getByRole("button", { name: "Files", exact: true }).click();
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Choose from your device" }).click();
  await (
    await chooser
  ).setFiles({
    name: previewKind === "pdf" ? "notes.pdf" : "notes.txt",
    mimeType: previewKind === "pdf" ? "application/pdf" : "text/plain",
    buffer: previewKind === "pdf" ? pdfBytes : Buffer.from("hello"),
  });
  await page.getByRole("button", { name: "Add 1 attachment" }).click();
  await expect(
    page
      .getByTestId("conversation-composer")
      .getByRole("button", { name: `Remove ${previewKind === "pdf" ? "notes.pdf" : "notes.txt"}` }),
  ).toBeVisible();
}
test("anchors the attachment popup above the composer with a dark backdrop", async ({
  page,
}) => {
  await cloud(page);
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto(`/home/${a}`);
  await page.getByRole("button", { name: "Add attachment" }).click();
  const dialog = page.getByRole("dialog", { name: "Attachments" });
  const composer = page.getByTestId("conversation-composer");
  const checkPosition = async () => {
    await expect
      .poll(async () => {
        const popup = await dialog.boundingBox();
        const input = await composer.boundingBox();
        return (
          !!popup &&
          !!input &&
          Math.abs(popup.x - input.x) < 2 &&
          popup.y + popup.height <= input.y &&
          popup.x + popup.width <= input.x + input.width + 2
        );
      })
      .toBe(true);
  };
  await checkPosition();
  await expect(
    page.getByRole("button", { name: "Dismiss attachments" }),
  ).toHaveCSS("background-color", "rgba(0, 0, 0, 0.55)");
  await page.getByRole("button", { name: "Files", exact: true }).click();
  await checkPosition();
});
test("sends files-only through the real composer and opens a private preview", async ({
  page,
}) => {
  const fixture = await cloud(page);
  await select(page);
  expect(fixture.uploads()).toBe(0);
  await page.getByRole("button", { name: "Send message" }).click();
  const attachment = page.getByRole("button", { name: "Open notes.txt preview" });
  await expect(attachment).toBeEnabled();
  await attachment.click();
  await expect(
    page.getByRole("dialog").getByText("hello", { exact: true }),
  ).toBeVisible();
  expect(fixture.uploads()).toBe(1);
  expect(fixture.requests.some((r) => r.endsWith(`/messages`))).toBe(false);
});
test("renders a PDF preview from normalized private bytes", async ({ page }) => {
  await cloud(page, false, "pdf");
  await select(page, "pdf");
  await page.getByRole("button", { name: "Send message" }).click();
  await page.getByRole("button", { name: /notes\.pdf/ }).click();
  const frame = page.getByRole("dialog").locator("iframe");
  await expect(frame).toBeVisible();
  await expect(frame).toHaveAttribute("src", /^blob:/);
  await expect(frame).not.toHaveAttribute("sandbox");
  const src = await frame.getAttribute("src");
  expect(await page.evaluate(async (url) => (await (await fetch(url!)).blob()).type, src)).toBe("application/pdf");
});
test("requires retry after upload failure and retains the draft across refresh", async ({
  page,
}) => {
  const fixture = await cloud(page, true);
  await select(page);
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(
    page.getByRole("button", { name: "Retry files & send" }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Retry files & send" }),
  ).toBeVisible();
  expect(fixture.uploads()).toBe(1);
  await page.getByRole("button", { name: "Retry files & send" }).click();
  await expect.poll(fixture.uploads).toBe(2);
  await expect
    .poll(() => fixture.requests.some((r) => r.endsWith("/send-files")))
    .toBe(true);
  await expect(
    page.getByRole("button", { name: "Open notes.txt preview" }),
  ).toBeEnabled();
});
