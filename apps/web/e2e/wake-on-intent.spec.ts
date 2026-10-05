import { expect, test, type Page } from "@playwright/test";

const responseText = "FND-009 proof response";
const cloudUrl = process.env.FND009_CLOUD_URL ?? "";
const simulatorUrl = process.env.FND009_SIMULATOR_URL ?? "";
const workspaceId = process.env.FND009_WORKSPACE_ID ?? "";
const allyAId = process.env.FND009_ALLY_A_ID ?? "";
const allyBId = process.env.FND009_ALLY_B_ID ?? "";
const conversationBId = process.env.FND009_CONVERSATION_B_ID ?? "";
const proofToken = process.env.FND009_PROOF_TOKEN ?? "";
const keepWarmSeconds = Number(process.env.FND009_KEEP_WARM_SECONDS ?? "8");

type SimulatorSnapshot = {
  machine_state: string;
  starts: number;
  stops: number;
  readiness: number;
  claims: number;
  completed: number;
  errors: number;
  held: boolean;
  hold_next: boolean;
};

function requireValue(name: string, value: string): string {
  if (!value) throw new Error(`${name} is required for the FND-009 proof`);
  return value;
}

async function snapshot(page: Page): Promise<SimulatorSnapshot> {
  const response = await page.context().request.get(`${simulatorUrl}/snapshot`, {
    headers: { Authorization: `Bearer ${proofToken}` },
  });
  expect(response.ok()).toBeTruthy();
  return (await response.json()) as SimulatorSnapshot;
}

async function waitForSnapshot(
  page: Page,
  predicate: (value: SimulatorSnapshot) => boolean,
  message: string,
): Promise<SimulatorSnapshot> {
  let latest: SimulatorSnapshot | null = null;
  await expect.poll(async () => {
    const current = await snapshot(page);
    latest = current;
    return predicate(current);
  }, { message, timeout: 30_000, intervals: [250, 500, 1_000] }).toBeTruthy();
  if (!latest) throw new Error("snapshot polling did not produce a result");
  return latest;
}

async function fakeSignIn(page: Page): Promise<void> {
  const baseURL = requireValue("PW_BASE_URL", test.info().project.use.baseURL ?? "");
  await page.goto(`${baseURL}/home/${allyAId}`, { waitUntil: "domcontentloaded" });
  const callbackUrl = await page.evaluate(async ({ cloud, ally }) => {
    const origin = window.location.origin;
    const csrfResponse = await fetch(`${cloud}/api/v1/auths/csrf`, {
      credentials: "include",
      headers: { Origin: origin },
    });
    if (!csrfResponse.ok) throw new Error(`csrf failed: ${csrfResponse.status}`);
    const csrf = csrfResponse.headers.get("X-CSRFToken");
    if (!csrf) throw new Error("csrf response did not include a token");
    const startResponse = await fetch(`${cloud}/api/v1/auths/sign-in/fake`, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        "Origin": origin,
        "X-CSRFToken": csrf,
      },
      body: JSON.stringify({ redirect_to: `/home/${ally}` }),
    });
    if (!startResponse.ok) throw new Error(`fake sign-in failed: ${startResponse.status}`);
    const envelope = await startResponse.json() as { data?: { redirect_url?: string } };
    const authorization = new URL(envelope.data?.redirect_url ?? "", cloud);
    const state = authorization.searchParams.get("state");
    if (!state) throw new Error("fake sign-in response did not include state");
    const callback = new URL("/api/v1/auths/callback/fake", cloud);
    callback.searchParams.set("state", state);
    callback.searchParams.set("code", "fake:fnd009-user|FND-009 Proof User");
    return callback.toString();
  }, { cloud: requireValue("FND009_CLOUD_URL", cloudUrl), ally: requireValue("FND009_ALLY_A_ID", allyAId) });
  await page.goto(callbackUrl, { waitUntil: "domcontentloaded" });
  await expect(page).toHaveURL(new RegExp(`/home/${allyAId}$`));
  await expect(page.locator("#ally-message")).toBeVisible();
}

async function sendBThroughBrowser(page: Page, content: string): Promise<void> {
  const status = await page.evaluate(async ({ cloud, workspace, conversation, value }) => {
    const csrfCookie = document.cookie
      .split(";")
      .map((part) => part.trim())
      .find((part) => part.startsWith("csrftoken="))
      ?.slice("csrftoken=".length);
    const response = await fetch(
      `${cloud}/api/v1/workspaces/${workspace}/conversations/${conversation}/messages`,
      {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "Origin": window.location.origin,
          "X-CSRFToken": csrfCookie ?? "",
          "Idempotency-Key": crypto.randomUUID(),
        },
        body: JSON.stringify({ content: value }),
      },
    );
    return response.status;
  }, {
    cloud: requireValue("FND009_CLOUD_URL", cloudUrl),
    workspace: requireValue("FND009_WORKSPACE_ID", workspaceId),
    conversation: requireValue("FND009_CONVERSATION_B_ID", conversationBId),
    value: content,
  });
  expect(status).toBe(201);
}

test("wakes on intent, streams the response, sleeps, and wakes on prompt", async ({ page }) => {
  requireValue("FND009_SIMULATOR_URL", simulatorUrl);
  requireValue("FND009_PROOF_TOKEN", proofToken);
  requireValue("FND009_ALLY_B_ID", allyBId);
  await fakeSignIn(page);

  const initial = await snapshot(page);
  expect(initial.machine_state).toBe("stopped");

  await page.locator("#ally-message").fill("First proof prompt");
  await waitForSnapshot(
    page,
    (value) => value.starts === 1 && value.readiness >= 1,
    "composing intent should start and ready the stopped Machine",
  );
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByTestId("activity-reply-3")).toContainText(responseText);

  await waitForSnapshot(
    page,
    (value) => value.machine_state === "stopped" && value.stops === 1,
    "idle keep-warm expiry should stop the Machine",
  );

  await page.locator("#ally-message").fill("Prompt fallback proof");
  await page.getByRole("button", { name: "Send message" }).click();
  await waitForSnapshot(
    page,
    (value) => value.starts === 2 && value.readiness >= 2,
    "the accepted prompt should wake a stopped Machine",
  );
  await expect(page.getByTestId("activity-reply-4")).toContainText(responseText);
  await waitForSnapshot(
    page,
    (value) => value.machine_state === "stopped" && value.stops === 2,
    "the second completed turn should also become idle",
  );

  const holdResponse = await page.context().request.post(`${simulatorUrl}/control/hold-next`, {
    headers: { Authorization: `Bearer ${proofToken}` },
  });
  expect(holdResponse.ok()).toBeTruthy();
  await sendBThroughBrowser(page, "Ally B active proof");
  const held = await waitForSnapshot(
    page,
    (value) => value.starts === 3 && value.held,
    "another Ally should hold active work on the shared Machine",
  );
  await page.waitForTimeout((keepWarmSeconds + 2) * 1_000);
  const whileHeld = await snapshot(page);
  expect(whileHeld.machine_state).toBe("started");
  expect(whileHeld.stops).toBe(held.stops);
  expect(whileHeld.completed).toBe(2);

  const releaseResponse = await page.context().request.post(`${simulatorUrl}/control/release`, {
    headers: { Authorization: `Bearer ${proofToken}` },
  });
  expect(releaseResponse.ok()).toBeTruthy();
  await waitForSnapshot(
    page,
    (value) => value.completed >= 3 && value.machine_state === "stopped" && value.stops === 3,
    "released active work should complete before idle stop",
  );
});
