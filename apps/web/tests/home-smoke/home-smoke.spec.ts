import { expect, test, type Page } from "@playwright/test";

const workspaceId = "00000000-0000-4000-8000-000000000001";
const allyId = "00000000-0000-4000-8000-000000000002";
const conversationId = "00000000-0000-4000-8000-000000000003";
const sentMessageId = "00000000-0000-4000-8000-000000000004";
const now = "2099-01-01T12:00:37Z";
const reply = "Keep this reply after reload.";
const assistantReply = "This assistant reply remains durable.";
const csrfToken = "a".repeat(32);
const routineId = "00000000-0000-4000-8000-000000000020";
const routineSchedule = { kind: "recurring", frequency: "daily", local_time: "09:00:00", timezone: "Europe/Berlin" };

type SessionMode = "signed-in" | "signed-out";

function success<T>(data: T) {
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
    appearance: { catalog_version: "v1", key: "ghosty:fd304f" },
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

async function fixtureCloud(page: Page, mode: SessionMode, withApproval = false, seedConversation = false, withActivity = false, withRoutine = false, withResult = false, withDeletion = false, approvalOptions?: { appearanceKey: string; preview: string }) {
  const fixtureAlly = () => ({ ...ally(), ...(approvalOptions ? { appearance: { catalog_version: "v1", key: approvalOptions.appearanceKey } } : {}) });
  let sent = seedConversation;
  let settings = { label: "chief of staff", show_label: false, settings_revision: 0 };
  let deletionAccepted = false;
  let deleted = false;
  let deletionStatusReads = 0;
  let sentRequest: { body: string | null; csrf: string | undefined } | null = null;
  let releaseSend: (() => void) | null = null;
  let approvalStatus = "pending";
  const approvalId = "00000000-0000-4000-8000-000000000010";
  const approval = () => ({ id: approvalId, message_id: sentMessageId, status: approvalStatus, expires_at: now, decided_at: approvalStatus === "pending" ? null : new Date().toISOString(), acknowledgement_deadline_at: approvalStatus === "pending" ? null : new Date(Date.now() + 30_000).toISOString() });
  const sibling = () => ({ ...ally(), id: "00000000-0000-4000-8000-000000000011", name: "Sage" });
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const headers = {
      "access-control-allow-origin": request.headers().origin ?? "http://127.0.0.1:3012",
      "access-control-allow-credentials": "true",
      "access-control-allow-headers": "content-type, idempotency-key, x-csrftoken",
      "access-control-allow-methods": "GET, POST, PATCH, OPTIONS",
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
      const allies = deleted
        ? [sibling()]
        : [{ ...fixtureAlly(), ...settings, ...(deletionAccepted ? { deletion_state: "pending" } : {}) }, ...(withDeletion ? [sibling()] : [])];
      return route.fulfill({ status: 200, headers, json: success({ allies }) });
    }
    if (url.pathname === `/api/v1/workspaces/${workspaceId}/allies/${allyId}/settings` && request.method() === "PATCH") {
      expect(request.headers()["x-csrftoken"]).toBe(csrfToken);
      const payload = request.postDataJSON();
      expect(payload.settings_revision).toBe(settings.settings_revision);
      settings = { ...payload, settings_revision: settings.settings_revision + 1 };
      return route.fulfill({ status: 200, headers, json: success({ ...fixtureAlly(), ...settings }) });
    }
    if (withDeletion && url.pathname === `/api/v1/workspaces/${workspaceId}/allies/${allyId}/deletion`) {
      if (request.method() === "POST") {
        expect(request.headers()["x-csrftoken"]).toBe(csrfToken);
        expect(request.postDataJSON()).toEqual({ confirmation: "Ada - deletes me" });
        deletionAccepted = true;
        return route.abort("failed");
      }
      deletionStatusReads += 1;
      if (deletionStatusReads >= 2) {
        deleted = true;
        return route.fulfill({ status: 200, headers, json: success({ ally_id: allyId, state: "complete", retryable: false, safe_error_code: "" }) });
      }
      return route.fulfill({ status: 202, headers, json: success({ ally_id: allyId, operation_id: "00000000-0000-4000-8000-000000000012", state: "pending", retryable: true, safe_error_code: "" }) });
    }
    if (url.pathname === `/api/v1/workspaces/${workspaceId}/allies/${allyId}`) {
      return route.fulfill({ status: 200, headers, json: success(fixtureAlly()) });
    }
    if (url.pathname === `/api/v1/workspaces/${workspaceId}/allies/${allyId}/conversation`) {
      const payload = conversation(sent);
      if (withRoutine) {
        payload.data.messages.push({ id: "00000000-0000-4000-8000-000000000021", sender: "user", content: "A later unrelated message", sequence: 2, status: "completed", created_at: "2099-01-01T12:05:00Z", retryable: false });
      }
      return route.fulfill({ status: 200, headers, json: withRoutine ? { ...payload, data: { ...payload.data, routine_items: [{
        id: routineId, kind: "created", routine_id: routineId, conversation_id: conversationId, source_message_id: sentMessageId,
        title_snapshot: "Morning check", routine_revision: 1, schedule_generation: 1, status: "created", schedule: routineSchedule,
        occurred_at: "2099-01-01T12:01:00Z", references: [],
      }, ...(withResult ? [{
        id: "00000000-0000-4000-8000-000000000025", kind: "result", routine_id: routineId, conversation_id: conversationId,
        title_snapshot: "A very long routine name that should truncate without hiding the status or time", routine_revision: 1, schedule_generation: 1,
        status: "changed", schedule: routineSchedule, occurred_at: "2099-01-01T12:06:00Z",
        run_id: "00000000-0000-4000-8000-000000000026", result_id: "00000000-0000-4000-8000-000000000025", result_insertion: "inserted", text: "**AI is great**", references: [],
      }] : [])] } } : payload });
    }
    if (withRoutine && url.pathname === `/api/v1/workspaces/${workspaceId}/routines/${routineId}`) {
      return route.fulfill({ status: 200, headers, json: success({
        id: routineId, responsible_ally_id: allyId, title: "Morning check", schedule: routineSchedule,
        revision: 1, schedule_generation: 1, schedule_state: "active", next_run_at: "2099-01-02T08:00:00Z", created_at: now, updated_at: now,
        workspace_id: workspaceId, owner_user_id: "00000000-0000-4000-8000-000000000005", binding_id: "00000000-0000-4000-8000-000000000007",
        main_conversation_id: conversationId, execution_prompt: "Check the latest price and report the result, even if unchanged.",
      }) });
    }
    if (url.pathname === `/api/v1/workspaces/${workspaceId}/conversations/${conversationId}/activities`) {
      const activities = withActivity && sent ? [{
        id: "00000000-0000-4000-8000-000000000011",
        message_id: sentMessageId,
        sequence: 1,
        conversation_turn_ordinal: 1,
        kind: "activity_started",
        text: "Terminal command",
        state: "completed",
        created_at: now,
        activity_kind: "terminal",
      }] : [];
      return route.fulfill({ status: 200, headers, json: success({
        conversation_id: conversationId,
        activities,
        state: "completed",
        last_contiguous_sequence: activities.length,
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
      const requestId = "00000000-0000-4000-8000-000000000030";
      const digest = `sha256:${"a".repeat(64)}`;
      return route.fulfill({ status: 200, headers, json: success({
        ...approval(), contract_version: "approval.v1", approval_request_id: requestId, preview_digest: digest,
        action_label: "Run code", action_preview: approvalOptions?.preview ?? "connect_knowledge_space(credential='[REDACTED]')",
        technical_details: { action_kind: "execute_code", action_label: "Run code", action_preview: approvalOptions?.preview ?? "connect_knowledge_space(credential='[REDACTED]')" },
        explanation: { version: "approval-explanation.v1", approval_request_id: requestId, preview_digest: digest, source: "model",
          action: "Connect your knowledge space", target: "Your selected knowledge service",
          consequence: "Your Ally will be able to read the notes you have shared", reason: "Your permission is needed to finish connecting" },
      }) });
    }
    if (url.pathname === `/api/v1/workspaces/${workspaceId}/conversations/${conversationId}/messages` && request.method() === "POST") {
      sentRequest = { body: request.postData(), csrf: request.headers()["x-csrftoken"] };
      if (withRoutine) await new Promise<void>((resolve) => { releaseSend = resolve; });
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
  return {
    sentRequest: () => sentRequest,
    releaseSend: () => releaseSend?.(),
    deletionStatusReads: () => deletionStatusReads,
  };
}

test("restores composer spacing after the mobile keyboard closes", async ({ page }, testInfo) => {
  await fixtureCloud(page, "signed-in");
  await page.goto(`/home/${allyId}`);
  const input = page.getByLabel("Message Ada");
  await expect(input).toBeVisible();
  const padding = () => input.evaluate(element => getComputedStyle(element.closest('[data-testid="conversation-composer"]')!.parentElement!).paddingBottom);
  const original = await padding();
  await input.fill("Keyboard regression check");
  await page.evaluate(() => {
    const height = window.visualViewport!.height - 300;
    Object.defineProperty(window, "innerHeight", { configurable: true, value: height });
    Object.defineProperty(window.visualViewport, "height", { configurable: true, value: height });
    window.visualViewport!.dispatchEvent(new Event("resize"));
  });
  await expect(page.getByTestId("conversation-frame-shell")).toHaveAttribute("data-keyboard-open", "");
  await expect.poll(padding).toBe(testInfo.project.name === "mobile" ? "8px" : original);
  await input.blur();
  await expect(page.getByTestId("conversation-frame-shell")).not.toHaveAttribute("data-keyboard-open");
  await expect.poll(padding).toBe(original);
});

test("redirects signed-out visitors home with Google sign-in available", async ({ page }) => {
  await fixtureCloud(page, "signed-out");
  await page.goto("/home");
  await expect(page).toHaveURL(new URL("/", page.url()).toString());
  await expect(page.getByRole("button", { name: "Continue with Google" })).toBeVisible();
});

for (const colorScheme of ["light", "dark"] as const) {
  test(`routine stays in its turn and confirms deletion in ${colorScheme} mode`, async ({ page }, testInfo) => {
    await page.emulateMedia({ colorScheme, reducedMotion: "reduce" });
    const fixture = await fixtureCloud(page, "signed-in", false, true, false, true);
    await page.goto(`/home/${allyId}`);
    const card = page.getByRole("button", { name: /Morning check/ });
    await expect(card).toBeVisible();
    await expect(card).not.toContainText("Europe/Berlin");
    await expect(card.locator(":scope > svg path")).toHaveCount(2);
    await card.screenshot({ path: testInfo.outputPath(`routine-card-${colorScheme}.png`) });
    const assertPosition = async () => {
      expect(await card.evaluate((element) => {
        const later = [...document.querySelectorAll("article")].find((article) => article.textContent?.includes("A later unrelated message"));
        return Boolean(later && (element.compareDocumentPosition(later) & Node.DOCUMENT_POSITION_FOLLOWING));
      })).toBe(true);
    };
    await assertPosition();
    await page.reload();
    await expect(card).toBeVisible();
    await assertPosition();
    await card.click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toHaveCount(1);
    await expect(dialog.getByText("Full prompt", { exact: true })).toBeVisible();
    await dialog.getByText("Full prompt", { exact: true }).click();
    await expect(dialog.getByText(/Check the latest price/)).toBeVisible();
    await expect(dialog.getByText("Revision", { exact: true })).toHaveCount(0);
    const box = await dialog.locator(":scope > section").boundingBox();
    const shell = await page.getByTestId("conversation-frame-shell").boundingBox();
    expect(box).not.toBeNull();
    expect(shell).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(shell!.x);
    expect(box!.x + box!.width).toBeLessThanOrEqual(shell!.x + shell!.width);
    if (testInfo.project.name === "desktop") {
      expect(box!.width).toBeGreaterThan(375);
      expect(Math.abs(box!.x + box!.width / 2 - (shell!.x + shell!.width / 2))).toBeLessThan(3);
      expect(Math.abs(box!.y + box!.height / 2 - (shell!.y + shell!.height / 2))).toBeLessThan(3);
    }
    await page.screenshot({ path: testInfo.outputPath(`routine-details-${colorScheme}.png`) });
    await dialog.getByRole("button", { name: "Delete", exact: true }).click();
    await expect(dialog).toHaveCount(1);
    await expect(dialog.getByRole("heading", { name: /Are you sure.*Morning check/ })).toBeVisible();
    await expect(dialog.getByRole("heading", { name: /Are you sure/ })).toHaveCSS("text-align", "center");
    expect(await dialog.locator(":scope > section").evaluate((element) => getComputedStyle(element).boxShadow.match(/rgba?\(/g)?.length)).toBe(1);
    expect(fixture.sentRequest()).toBeNull();
    await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
    expect(fixture.sentRequest()).toBeNull();
    await expect(dialog.getByRole("button", { name: "Delete", exact: true })).toBeFocused();
    await dialog.getByRole("button", { name: "Delete", exact: true }).click();
    await page.screenshot({ path: testInfo.outputPath(`routine-delete-${colorScheme}.png`) });
    await dialog.getByRole("button", { name: "Delete", exact: true }).click();
    await expect.poll(() => fixture.sentRequest()).not.toBeNull();
    await expect(dialog.getByRole("button", { name: "Cancel", exact: true })).toBeDisabled();
    await expect(dialog.getByRole("button", { name: "Close", exact: true })).toBeDisabled();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeVisible();
    const request = JSON.parse(fixture.sentRequest()!.body!);
    expect(request.content).toBe(`I confirm: delete the routine [Morning check](#routine/${routineId}).`);
    expect(request.routine_action).toMatchObject({ action: "delete", routine_id: routineId, expected_revision: 1, confirmed: true });
    expect(request.timezone).toBe(await page.evaluate(() => Intl.DateTimeFormat().resolvedOptions().timeZone));
    fixture.releaseSend();
    await expect(dialog).toHaveCount(0);
  });
}

for (const colorScheme of ["light", "dark"] as const) {
test(`shows a real conversation approval and records the choice in ${colorScheme} mode`, async ({ page }, testInfo) => {
  if (testInfo.project.name === "mobile") await page.setViewportSize({ width: 375, height: 812 });
  await page.emulateMedia({ colorScheme, reducedMotion: "reduce" });
  await fixtureCloud(page, "signed-in", true);
  await page.goto(`/home/${allyId}`);
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText("Connect your knowledge space")).toBeVisible();
  await expect(dialog.getByText("Your selected knowledge service")).toBeVisible();
  const preview = dialog.locator("pre");
  await expect(preview).not.toBeVisible();
  const disclosure = dialog.getByText("View technical details", { exact: true });
  await disclosure.click();
  await expect(preview).toBeVisible();
  await expect(preview).toHaveText("connect_knowledge_space(credential='[REDACTED]')");
  await disclosure.click();
  const approve = dialog.getByRole("button", { name: "Approve", exact: true });
  const reject = dialog.getByRole("button", { name: "Reject", exact: true });
  for (const button of [approve, reject]) {
    const geometry = await button.evaluate((element) => ({ height: element.getBoundingClientRect().height, radius: getComputedStyle(element).borderRadius, background: getComputedStyle(element).backgroundColor }));
    expect(geometry.height).toBeGreaterThanOrEqual(48);
    expect(parseFloat(geometry.radius)).toBeGreaterThanOrEqual(24);
    expect(geometry.background).not.toBe("rgba(0, 0, 0, 0)");
  }
  await dialog.getByRole("button", { name: "Close", exact: true }).focus();
  await expect(dialog.getByRole("button", { name: "Close", exact: true })).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  expect(await dialog.evaluate((element) => document.activeElement === document.body || element.contains(document.activeElement))).toBe(true);
  await page.keyboard.press("Tab");
  await expect(dialog.getByRole("button", { name: "Close", exact: true })).toBeFocused();
  await page.screenshot({ path: testInfo.outputPath(`approval-${colorScheme}.png`) });
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await page.getByRole("button", { name: "Approval needed", exact: true }).click();
  await expect(preview).not.toBeVisible();
  await dialog.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Decision recorded · Waiting for Ally", exact: true })).toBeFocused();
  await expect(page.getByText("Previous approvals")).toHaveCount(0);
  await page.getByRole("button", { name: "Decision recorded · Waiting for Ally", exact: true }).click();
  await expect(dialog.getByRole("button", { name: "Approve", exact: true })).toHaveCount(0);
  await expect(dialog.getByRole("button", { name: "Reject", exact: true })).toHaveCount(0);
  await expect(dialog.getByText("Connect your knowledge space")).toBeVisible();
});
}

test("real conversation approval scrolls complete technical details on a narrow screen", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await page.emulateMedia({ colorScheme: "light", reducedMotion: "reduce" });
  const safePreview = "print('Synthetic safe preview')\n".repeat(200);
  await fixtureCloud(page, "signed-in", true, false, false, false, false, false, { appearanceKey: "ghosty:ff5800", preview: safePreview });
  await page.goto(`/home/${allyId}`);
  const dialog = page.getByRole("dialog");
  const approve = dialog.getByRole("button", { name: "Approve", exact: true });
  await expect(approve).toHaveCSS("background-color", "rgb(255, 88, 0)");
  await dialog.getByText("View technical details", { exact: true }).click();
  await expect(dialog.locator("pre")).toHaveText(safePreview);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await approve.scrollIntoViewIfNeeded();
  await expect(approve).toBeInViewport();
  await page.screenshot({ path: testInfo.outputPath("approval-narrow-details.png") });
});

test("keeps local message times outside bubbles without changing bubble geometry", async ({ page }) => {
  await fixtureCloud(page, "signed-in");
  await page.goto(`/home/${allyId}`);
  await page.getByLabel("Message Ada").fill(reply);
  await page.getByRole("button", { name: "Send message" }).click();

  const userBubble = page.locator("article").filter({ hasText: reply });
  const assistantMessage = page.locator("article").filter({ hasText: assistantReply });
  await expect(userBubble).toBeVisible();
  await expect(assistantMessage).toBeVisible();
  expect(await assistantMessage.evaluate((element) => getComputedStyle(element).marginTop)).toBe("24px");

  const layout = () => page.evaluate(({ reply, assistantReply }) => {
    const articles = [...document.querySelectorAll("article")];
    const bounds = (element: Element | null) => {
      const rect = element?.getBoundingClientRect();
      return rect ? { x: rect.x, y: rect.y, width: rect.width, height: rect.height } : null;
    };
    const canvas = document.querySelector('[data-testid="conversation-frame-canvas"]');
    return {
      user: bounds(articles.find((article) => article.textContent?.includes(reply)) ?? null),
      assistant: bounds(articles.find((article) => article.textContent?.includes(assistantReply)) ?? null),
      composer: bounds(document.querySelector('[data-testid="conversation-composer"]')),
      canvas: canvas ? { height: canvas.scrollHeight, top: canvas.scrollTop } : null,
    };
  }, { reply, assistantReply });

  for (const message of [userBubble, assistantMessage]) {
    await message.scrollIntoViewIfNeeded();
    const timestamp = message.locator("xpath=following-sibling::time[1]");
    await expect(timestamp).toHaveCount(1);
    expect(await message.locator("time").count()).toBe(0);
    const before = await message.evaluate((element) => {
      const bounds = element.getBoundingClientRect();
      return { width: bounds.width, height: bounds.height, radius: getComputedStyle(element).borderRadius };
    });
    const beforeLayout = await layout();

    await message.click();
    await expect(timestamp).toHaveAttribute("data-visible", "true");
    await page.waitForTimeout(90);
    expect(await layout()).toEqual(beforeLayout);
    await page.waitForTimeout(250);
    const after = await message.evaluate((element) => {
      const bounds = element.getBoundingClientRect();
      return { width: bounds.width, height: bounds.height, radius: getComputedStyle(element).borderRadius };
    });
    const [messageBox, timestampBox, paintedTimestamp, label] = await Promise.all([
      message.boundingBox(),
      timestamp.boundingBox(),
      timestamp.evaluate((element) => {
        const range = document.createRange();
        range.selectNodeContents(element);
        const bounds = range.getBoundingClientRect();
        return { x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height };
      }),
      timestamp.textContent(),
    ]);
    const expected = await timestamp.evaluate((element) => new Intl.DateTimeFormat([], { timeStyle: "short" }).format(new Date(element.getAttribute("datetime")!)));

    expect(after).toEqual(before);
    expect(await layout()).toEqual(beforeLayout);
    expect(timestampBox!.height).toBe(0);
    expect(paintedTimestamp.y).toBeGreaterThanOrEqual(messageBox!.y + messageBox!.height);
    expect(paintedTimestamp.height).toBeGreaterThan(0);
    expect(paintedTimestamp.x).toBeGreaterThanOrEqual(0);
    expect(paintedTimestamp.x + paintedTimestamp.width).toBeLessThanOrEqual(page.viewportSize()!.width);
    expect(label).toBe(expected);
    expect(label).not.toBe(await timestamp.evaluate((element) => new Intl.DateTimeFormat([], { timeStyle: "medium" }).format(new Date(element.getAttribute("datetime")!))));
    await page.waitForTimeout(3_000);
    await expect(timestamp).toHaveAttribute("data-visible", "false");
    expect(await layout()).toEqual(beforeLayout);
  }
});

test("keeps revealed timestamps clear of same-row activity and approval content", async ({ page }) => {
  for (const withActivity of [true, false]) {
    const scenario = withActivity ? page : await page.context().newPage();
    await fixtureCloud(scenario, "signed-in", true, true, withActivity);
    await scenario.goto(`/home/${allyId}`);

    const dialog = scenario.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await scenario.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible();

    const assistantMessage = scenario.locator("article").filter({ hasText: assistantReply });
    const timestamp = assistantMessage.locator("xpath=following-sibling::time[1]");
    const follower = withActivity
      ? scenario.locator("details").filter({ hasText: "1 activity" })
      : scenario.getByRole("button", { name: "Approval needed", exact: true }).locator("xpath=..");
    await expect(assistantMessage).toBeVisible();
    await expect(timestamp).toHaveCount(1);
    await expect(follower).toBeVisible();

    await assistantMessage.click();
    await expect(timestamp).toHaveAttribute("data-visible", "true");
    await scenario.waitForTimeout(250);
    const geometry = await timestamp.evaluate((element) => {
      const range = document.createRange();
      range.selectNodeContents(element);
      const painted = range.getBoundingClientRect();
      const next = element.nextElementSibling;
      return {
        paintedBottom: painted.bottom,
        followerTop: next?.getBoundingClientRect().top ?? null,
        followerMarginTop: next ? getComputedStyle(next).marginTop : null,
      };
    });
    expect(geometry.followerMarginTop).toBe("18px");
    expect(geometry.followerTop).not.toBeNull();
    expect(geometry.followerTop!).toBeGreaterThanOrEqual(geometry.paintedBottom);

    if (!withActivity) await scenario.close();
  }
});

test("beta settings navigation and roster controls", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await fixtureCloud(page, "signed-in");
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/home");
  await expect(page.getByRole("button", { name: "Recipes", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "My allies", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Routines", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Recipes", exact: true }).click();
  await expect(page.getByText("Recipes are coming soon.")).toBeVisible();
  await page.getByRole("button", { name: "Dismiss notification" }).click();
  await page.getByRole("navigation", { name: "Choose an Ally" }).getByRole("link").click();
  await page.getByRole("button", { name: "Ada settings", exact: true }).filter({ visible: true }).click();
  await expect(page.getByRole("dialog", { name: "Ada settings" })).toBeVisible();
  await page.goto(`/allies/${allyId}/settings`);
  await expect(page.getByRole("heading", { name: "Ally settings" })).toBeVisible();
  await expect(page.getByText("Helpful and concise.")).toBeVisible();
  await expect(page.getByLabel("Label", { exact: true })).toHaveAttribute("readonly", "");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("ally-settings-dark.png"), fullPage: true });
  await page.getByRole("button", { name: "Back", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/home/${allyId}$`));
  await page.goto("/account");
  await expect(page.getByRole("heading", { name: "Settings", exact: true })).toBeVisible();
  await expect(page.getByLabel("Display name", { exact: true })).toHaveValue("Smoke User");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("account-settings-dark.png"), fullPage: true });
  await page.emulateMedia({ colorScheme: "light" });
  await page.screenshot({ path: testInfo.outputPath("account-settings-light.png"), fullPage: true });
  await page.getByRole("button", { name: "Back", exact: true }).click();
  await expect(page).toHaveURL(/\/home$/);
  expect(errors).toEqual([]);
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
  await expect(page.getByTestId("onboarding-introduction")).toBeVisible();
});

test("centers the shape selector on tall screens", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1600 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await fixtureCloud(page, "signed-in");
  await page.goto("/home/new");
  await expect(page.getByTestId("onboarding-introduction")).toHaveCount(0);
  await page.getByTestId("job-input").fill("Help me keep track of my projects and make time for learning every week.");
  await page.getByTestId("next-button").click();
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
  const timezone = await page.evaluate(() => Intl.DateTimeFormat().resolvedOptions().timeZone);
  await expect.poll(cloud.sentRequest).toEqual({ body: JSON.stringify({ content: reply, timezone }), csrf: csrfToken });
  await expect(page.locator("article").filter({ hasText: reply })).toBeVisible();
  await expect(page.getByTestId("activity-reply-1").locator("p")).toHaveText(assistantReply);
  await page.reload();
  await expect(page.locator("article").filter({ hasText: reply })).toBeVisible();
  await expect(page.getByTestId("activity-reply-1").locator("p")).toHaveText(assistantReply);
  expect(cloudinaryRequests).toEqual([]);
  await page.goto("/home/new");
  await expect(page.getByTestId("job-description")).toBeVisible();
});

test("edits an Ally label, opts into roster display, and persists hiding it", async ({ page }, testInfo) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await fixtureCloud(page, "signed-in");
  await page.goto("/home");
  await expect(page.getByText("chief of staff", { exact: true })).toHaveCount(0);
  await page.getByRole("link", { name: /Ada/ }).click();
  const settingsButton = page.getByRole("button", { name: "Ada settings", exact: true });
  await settingsButton.click();
  const dialog = page.getByRole("dialog", { name: "Ada settings" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel("Label", { exact: true })).toHaveValue("chief of staff");
  await expect(dialog.getByRole("checkbox", { name: /Show label/ })).not.toBeChecked();
  await dialog.getByRole("button", { name: "Close", exact: true }).focus();
  await page.keyboard.press("Tab");
  await expect(dialog.getByLabel("Label", { exact: true })).toBeFocused();
  await dialog.getByLabel("Label", { exact: true }).fill("calendar manager");
  await dialog.getByRole("checkbox", { name: /Show label/ }).check();
  await dialog.getByRole("button", { name: "Save", exact: true }).click();
  await expect(dialog.getByRole("status")).toHaveText("Settings saved.");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("ally-settings.png"), fullPage: true });
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(settingsButton).toBeFocused();
  await page.goto("/home");
  await page.reload();
  await expect(page.getByRole("link", { name: /Ada/ }).getByText("calendar manager", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: /Ada/ }).click();
  await settingsButton.click();
  await dialog.getByRole("checkbox", { name: /Show label/ }).uncheck();
  await dialog.getByRole("button", { name: "Save", exact: true }).click();
  await expect(dialog.getByRole("status")).toHaveText("Settings saved.");
  await page.goto("/home");
  await page.reload();
  await expect(page.getByText("calendar manager", { exact: true })).toHaveCount(0);
});

test("keeps an accepted Ally deletion pending through a lost response and removes only that Ally", async ({ page }) => {
  const fixture = await fixtureCloud(page, "signed-in", false, false, false, false, false, true);
  await page.goto(`/home/${allyId}`);
  const settingsButton = page.getByRole("button", { name: "Ada settings", exact: true });
  await settingsButton.click();
  const dialog = page.getByRole("dialog", { name: "Ada settings" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Delete Ally", exact: true }).click();
  const confirmation = dialog.locator("#ally-delete-confirmation");
  await expect(confirmation).toBeFocused();
  await expect(dialog.getByText("Ada - deletes me", { exact: true })).toBeVisible();
  await confirmation.fill("Ada - deletes me");
  await dialog.getByRole("button", { name: "Delete Ally", exact: true }).click();

  await expect(dialog.getByText("We couldn't confirm the request. We'll keep checking its status.")).toBeVisible();
  await expect(page.locator('[data-ally-deletion-state="pending"]')).toHaveCount(1);
  await dialog.getByRole("button", { name: "Close", exact: true }).last().click();
  await expect(dialog).toHaveCount(0);

  await page.evaluate(() => Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" }));
  await page.waitForTimeout(2_200);
  expect(fixture.deletionStatusReads()).toBe(0);
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await page.waitForTimeout(2_200);
  expect(fixture.deletionStatusReads()).toBeGreaterThanOrEqual(1);

  await page.getByRole("button", { name: "Refresh deletion status", exact: true }).click();
  await expect(page.getByRole("link", { name: /Sage/ })).toBeVisible();
  await expect(page.getByRole("link", { name: /Ada/ })).toHaveCount(0);
});

for (const colorScheme of ["light", "dark"] as const) {
  test(`compact routine result in ${colorScheme} mode`, async ({ page }, testInfo) => {
    await page.emulateMedia({ colorScheme });
    await fixtureCloud(page, "signed-in", false, true, false, true, true);
    await page.goto(`/home/${allyId}`);
    const run = page.getByRole("region", { name: "Routine run", exact: true });
    await expect(run).toBeVisible();
    const row = run.getByRole("button", { name: /Succeeded/ });
    await expect(row).toBeVisible();
    expect(await row.evaluate(el => el.parentElement?.querySelector("time") === null)).toBe(true);
    await expect(run.locator("article")).toHaveText("AI is great");
    expect(await row.locator("span").first().evaluate(el => el.scrollWidth > el.clientWidth)).toBe(true);
    expect(await run.evaluate(el => getComputedStyle(el).marginTop)).toBe("24px");
    const rowBox = await row.boundingBox();
    const messageBox = await run.locator("article").boundingBox();
    expect(messageBox!.y - rowBox!.y - rowBox!.height).toBeGreaterThanOrEqual(16);
    await run.locator("article").click();
    await expect(run.locator("time")).toHaveAttribute("data-visible", "true");
    const timestampBox = await run.locator("time").boundingBox();
    expect(timestampBox!.y - messageBox!.y - messageBox!.height).toBeCloseTo(4, 0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await run.screenshot({ path: testInfo.outputPath(`compact-result-${colorScheme}.png`) });
    await row.click();
    await expect(page.getByRole("dialog")).toContainText("Completed");
  });
}
