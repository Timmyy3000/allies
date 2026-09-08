import { expect, test, type Page } from "@playwright/test";

const workspaceId = "00000000-0000-4000-8000-000000000001";
const allyId = "00000000-0000-4000-8000-000000000002";
const conversationId = "00000000-0000-4000-8000-000000000003";
const sentMessageId = "00000000-0000-4000-8000-000000000004";
const now = "2099-01-01T12:00:00Z";
const reply = "Keep this reply after reload.";
const assistantReply = "This assistant reply remains durable.";
const csrfToken = "a".repeat(32);

type SessionMode = "signed-in" | "signed-out";

function success(data: unknown) {
  return { status: "success", message: "ok", data };
}

function account() {
  return success({
    user: { id: "00000000-0000-4000-8000-000000000005" },
    profile: { display_name: "Smoke User", avatar_url: null },
    session: { id: "00000000-0000-4000-8000-000000000006", expires_at: "2099-01-02T12:00:00Z" },
    workspace: { id: workspaceId, name: "Smoke workspace", role: "owner", capabilities: ["profile.read", "profile.write"] },
  });
}

function ally() {
  return {
    id: allyId,
    binding_id: "00000000-0000-4000-8000-000000000007",
    operation_id: "00000000-0000-4000-8000-000000000008",
    name: "Ada",
    job: "Planning partner",
    personality: "Helpful and concise.",
    appearance: { catalog_version: "v1", key: "ghosty" },
    provisioning_state: "bound",
    retryable: false,
  };
}

function conversation(sent: boolean) {
  const messages = sent ? [{
    id: sentMessageId,
    sender: "user",
    content: reply,
    sequence: 1,
    status: "completed",
    created_at: now,
    retryable: false,
  }] : [];
  const assistantReplies = sent ? [{
    id: "00000000-0000-4000-8000-000000000009",
    source_message_id: sentMessageId,
    conversation_turn_ordinal: 1,
    content: assistantReply,
    status: "completed",
    has_full_prefix: true,
    is_truncated: false,
    created_at: now,
    updated_at: now,
  }] : [];
  return success({ id: conversationId, ally_id: allyId, messages, assistant_replies: assistantReplies, next_cursor: null });
}

async function fixtureCloud(page: Page, mode: SessionMode, withApproval = false) {
  let sent = false;
  let sentRequest: { body: string | null; csrf: string | undefined } | null = null;
  let approvalStatus = "pending";
  const approvalId = "00000000-0000-4000-8000-000000000010";
  const approval = () => ({ id: approvalId, message_id: sentMessageId, status: approvalStatus, expires_at: now, decided_at: approvalStatus === "pending" ? null : new Date().toISOString(), acknowledgement_deadline_at: approvalStatus === "pending" ? null : new Date(Date.now() + 30_000).toISOString() });
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const headers = {
      "access-control-allow-origin": request.headers().origin ?? "http://127.0.0.1:3012",
      "access-control-allow-credentials": "true",
      "access-control-allow-headers": "content-type, idempotency-key, x-csrftoken",
      "access-control-allow-methods": "GET, POST, OPTIONS",
      "access-control-expose-headers": "x-csrftoken",
    };
    if (request.method() === "OPTIONS") return route.fulfill({ status: 204, headers });
    if (url.pathname === "/api/v1/auths/me") {
      return route.fulfill(mode === "signed-in"
        ? { status: 200, headers, json: account() }
        : { status: 401, headers, json: { status: "error", message: "Sign in required" } });
    }
    if (mode !== "signed-in") return route.fulfill({ status: 401, headers, json: { status: "error", message: "Sign in required" } });
    if (url.pathname === "/api/v1/auths/csrf") {
      return route.fulfill({ status: 204, headers: { ...headers, "x-csrftoken": csrfToken } });
    }
    if (url.pathname === `/api/v1/workspaces/${workspaceId}/allies`) {
      return route.fulfill({ status: 200, headers, json: success({ allies: [ally()] }) });
    }
    if (url.pathname === `/api/v1/workspaces/${workspaceId}/allies/${allyId}/conversation`) {
      return route.fulfill({ status: 200, headers, json: conversation(sent) });
    }
    if (url.pathname === `/api/v1/workspaces/${workspaceId}/conversations/${conversationId}/activities`) {
      return route.fulfill({ status: 200, headers, json: success({
        conversation_id: conversationId,
        activities: [],
        state: "completed",
        last_contiguous_sequence: 0,
      }) });
    }
    if (url.pathname.endsWith(`/conversations/${conversationId}/approvals`)) {
      return route.fulfill({ status: 200, headers, json: success({ approvals: withApproval ? [approval()] : [] }) });
    }
    if (withApproval && url.pathname.includes(`/approvals/${approvalId}`)) {
      if (request.method() === "POST") {
        expect(request.headers()["x-csrftoken"]).toBe(csrfToken);
        expect(request.headers()["idempotency-key"]).toBeTruthy();
        expect(request.postDataJSON()).toEqual({ decision: "approve" });
        approvalStatus = "decision_recorded";
      }
      return route.fulfill({ status: 200, headers, json: success({ ...approval(), action_label: "Connect a knowledge space", action_preview: "Connect to the selected knowledge space using the supplied credential." }) });
    }
    if (url.pathname === `/api/v1/workspaces/${workspaceId}/conversations/${conversationId}/messages` && request.method() === "POST") {
      sentRequest = { body: request.postData(), csrf: request.headers()["x-csrftoken"] };
      sent = true;
      return route.fulfill({ status: 201, headers, json: success({
        conversation_id: conversationId,
        message: {
          id: sentMessageId,
          sender: "user",
          content: reply,
          sequence: 1,
          status: "completed",
          created_at: now,
          retryable: false,
        },
        execution: null,
        replayed: false,
      }) });
    }
    return route.fulfill({ status: 404, headers, json: { status: "error", message: `Unhandled ${url.pathname}` } });
  });
  return { sentRequest: () => sentRequest };
}

test("redirects signed-out visitors to sign-in", async ({ page }) => {
  await fixtureCloud(page, "signed-out");
  await page.goto("/home");
  await expect(page).toHaveURL(/\/sign-in\?returnTo=%2Fhome$/);
});

test("shows a real conversation approval and records the choice before runtime acknowledgement", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await fixtureCloud(page, "signed-in", true);
  await page.goto(`/home/${allyId}`);
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText("Connect a knowledge space")).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Close", exact: true })).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  expect(await dialog.evaluate((element) => document.activeElement === document.body || element.contains(document.activeElement))).toBe(true);
  await page.keyboard.press("Tab");
  await expect(dialog.getByRole("button", { name: "Close", exact: true })).toBeFocused();
  await page.screenshot({ path: testInfo.outputPath("approval-mobile.png") });
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await page.getByRole("button", { name: "Approval needed", exact: true }).click();
  await dialog.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(dialog.getByText("Decision recorded · Waiting for Ally")).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Approve", exact: true })).toHaveCount(0);
});

test("keeps the landing page continuous on a short phone", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 667 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await fixtureCloud(page, "signed-out");
  await page.goto("/");
  const storyCopy = page.locator(".landing-story-copy:visible");
  const landingFooter = page.locator(".landing-footer:visible");
  await expect(storyCopy).toHaveCSS("overflow-y", "visible");
  await expect(landingFooter).toHaveCSS("position", "static");
  const documentHeight = await page.evaluate(() => document.documentElement.scrollHeight);
  expect(documentHeight).toBeGreaterThan(667);
  const cta = page.getByRole("button", { name: "Meet your first ally" });
  await cta.scrollIntoViewIfNeeded();
  await expect(cta).toBeVisible();
  const ctaBox = await cta.boundingBox();
  const footerBox = await landingFooter.boundingBox();
  expect(ctaBox!.y + ctaBox!.height).toBeLessThan(footerBox!.y);
  await landingFooter.scrollIntoViewIfNeeded();
  await expect(landingFooter).toBeInViewport();
  expect(await page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
  await cta.click();
  await expect(page.getByTestId("name-ally")).toBeVisible();
});

test("centers the shape selector on tall screens", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1600 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await fixtureCloud(page, "signed-in");
  await page.goto("/home/new");
  await page.getByTestId("ally-name-input").fill("Layout test");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  const avatar = page.locator(".onboarding-look-avatar-window");
  await expect(avatar).toBeVisible();
  const stage = await page.getByTestId("avatar-carousel").boundingBox();
  const avatarBox = await avatar.boundingBox();
  const dots = await page.locator(".onboarding-look-dots").boundingBox();
  const colors = await page.getByTestId("color-row").boundingBox();
  const spaceAbove = avatarBox!.y - stage!.y;
  const spaceBelow = colors!.y - (dots!.y + dots!.height);
  expect(spaceAbove).toBeGreaterThan(100);
  expect(Math.abs(spaceAbove - spaceBelow)).toBeLessThan(2);
});

test("keeps Make an ally near the bottom of the mobile roster", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 667 });
  await fixtureCloud(page, "signed-in");
  await page.goto("/home");
  const button = page.getByRole("button", { name: "Make an Ally", exact: true });
  await expect(button).toBeVisible();
  const box = await button.boundingBox();
  expect(667 - (box!.y + box!.height)).toBeGreaterThanOrEqual(16);
  expect(667 - (box!.y + box!.height)).toBeLessThanOrEqual(24);
});

test("opens an Ally and keeps a sent reply after reload", async ({ page }) => {
  const cloudinaryRequests: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).hostname === "res.cloudinary.com") cloudinaryRequests.push(request.url());
  });
  const cloud = await fixtureCloud(page, "signed-in");
  await page.goto("/home");
  await page.getByRole("link", { name: /Ada/ }).click();
  await expect(page).toHaveURL(new RegExp(`/home/${allyId}$`));
  const composer = page.locator("#ally-message");
  await expect(composer).toBeEnabled();
  await composer.fill(reply);
  await page.getByRole("button", { name: "Send message" }).click();
  await expect.poll(cloud.sentRequest).toEqual({ body: JSON.stringify({ content: reply }), csrf: csrfToken });
  await expect(page.locator("article").filter({ hasText: reply })).toBeVisible();
  await expect(page.getByTestId("activity-reply-1")).toHaveText(assistantReply);
  await page.reload();
  await expect(page.locator("article").filter({ hasText: reply })).toBeVisible();
  await expect(page.getByTestId("activity-reply-1")).toHaveText(assistantReply);
  expect(cloudinaryRequests).toEqual([]);
  await page.goto("/home/new");
  await expect(page.getByTestId("name-ally")).toBeVisible();
});
