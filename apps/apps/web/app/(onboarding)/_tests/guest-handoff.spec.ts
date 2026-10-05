import { expect, test } from "@playwright/test";

const workspaceId = "00000000-0000-4000-8000-000000000001";
const allyId = "00000000-0000-4000-8000-000000000002";
const attempt = "a".repeat(32);
const conversationId = "00000000-0000-4000-8000-000000000009";
const greeting = "Hi, I’m Mira. Let’s plan your day.";
const success = (data: unknown) => ({ status: "success", message: "ok", data });

for (const mode of ["light", "dark"] as const) {
  test(`guest preview survives Google handoff (${mode})`, async ({ page, baseURL }, testInfo) => {
    test.setTimeout(90_000);
    await page.setViewportSize(mode === "dark" ? { width: 1280, height: 900 } : { width: 390, height: 844 });
    await page.emulateMedia({ colorScheme: mode, reducedMotion: "reduce" });
    const hydrationErrors: string[] = [];
    page.on("console", (message) => { if (/hydration|hydrating/i.test(message.text())) hydrationErrors.push(message.text()); });
    let signedIn = false;
    let createBody: Record<string, unknown> | undefined;
    let attempts = 0;
    let attemptBody: Record<string, unknown> | undefined;
    let creations = 0;
    const ally = {
      id: allyId, binding_id: "00000000-0000-4000-8000-000000000007", operation_id: "00000000-0000-4000-8000-000000000008",
      name: "Mira", job: "Help me plan my day", personality: "Be concise,", appearance: { catalog_version: "v1", key: "ghosty:0d92fd" },
      provisioning_state: "bound", retryable: false,
    };
    const account = success({
      user: { id: "00000000-0000-4000-8000-000000000005" },
      profile: { display_name: "Test", avatar_url: null },
      session: { id: "00000000-0000-4000-8000-000000000006", expires_at: "2099-01-02T12:00:00Z" },
      workspace: { id: workspaceId, name: "Test workspace", role: "owner", capabilities: [] },
    });
    await page.route("https://onboarding-auth.example.test/**", (route) => route.fulfill({
      status: 302, headers: { location: `${baseURL}/auth/return?returnTo=%2F` },
    }));
    await page.route("**/api/v1/**", async (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      const headers = {
        "access-control-allow-origin": request.headers().origin ?? baseURL!,
        "access-control-allow-credentials": "true",
        "access-control-allow-headers": "content-type, idempotency-key, x-csrftoken",
        "access-control-allow-methods": "GET, POST, OPTIONS",
        "access-control-expose-headers": "x-csrftoken",
      };
      if (request.method() === "OPTIONS") return route.fulfill({ status: 204, headers });
      if (path === "/api/v1/auths/csrf") return route.fulfill({ status: 204, headers: { ...headers, "x-csrftoken": attempt } });
      if (path === "/api/v1/auths/me") return route.fulfill(signedIn
        ? { status: 200, headers, json: account }
        : { status: 401, headers, json: { status: "error", message: "Sign in required" } });
      if (path === "/api/v1/onboarding/attempts") {
        attempts += 1;
        attemptBody = request.postDataJSON();
        expect(request.headers()["x-csrftoken"]).toBe(attempt);
        return route.fulfill({ status: 200, headers, json: success({ attempt_token: attempt, greeting }) });
      }
      if (path.includes("/auths/") && path.includes("google")) {
        signedIn = true;
        return route.fulfill({ status: 200, headers, json: success({ redirect_url: "https://onboarding-auth.example.test/callback" }) });
      }
      if (path === `/api/v1/workspaces/${workspaceId}/allies` && request.method() === "POST") {
        creations += 1;
        createBody = request.postDataJSON();
        expect(request.headers()["idempotency-key"]).toMatch(/^ally-create-/);
        return route.fulfill({ status: 201, headers, json: success(ally) });
      }
      if (path === `/api/v1/workspaces/${workspaceId}/allies`) return route.fulfill({ status: 200, headers, json: success({ allies: [ally] }) });
      if (path === `/api/v1/workspaces/${workspaceId}/allies/${allyId}/conversation`) {
        return route.fulfill({ status: 200, headers, json: success({
          id: conversationId, ally_id: allyId, next_cursor: null, assistant_replies: [],
          messages: [greeting, "Help me plan tomorrow."].map((content, index) => ({
            id: `00000000-0000-4000-8000-00000000001${index}`, sender: index ? "user" : "assistant", content,
            sequence: index + 1, status: "completed", created_at: "2099-01-01T12:00:00Z", retryable: false,
          })),
        }) });
      }
      if (path.endsWith("/activities")) {
        return route.fulfill({ status: 200, headers, json: success({
          conversation_id: conversationId, activities: [], state: "completed", last_contiguous_sequence: 0,
        }) });
      }
      return route.fulfill({ status: 404, headers, json: { status: "error", message: "Test endpoint unavailable" } });
    });
    await page.goto("/");
    await expect(page.locator("body")).toHaveCSS("background-color", mode === "dark" ? "rgb(17, 17, 17)" : "rgb(255, 255, 255)");
    await page.getByRole("button", { name: "Meet your first ally" }).click();
    await expect(page.getByTestId("onboarding-introduction")).toBeVisible();
    await expect(page.getByTestId("next-button")).toBeInViewport();
    await page.getByTestId("onboarding-introduction").screenshot({ path: testInfo.outputPath("introduction.png"), animations: "disabled" });
    await page.getByTestId("next-button").click();
    await expect(page.getByTestId("next-button")).toBeDisabled();
    await page.getByRole("textbox", { name: "Ally job" }).fill("Help me plan my day");
    await page.getByTestId("next-button").click();
    await expect(page.getByText("Add a little detail, or continue.")).toBeVisible();
    await page.getByTestId("job-description").screenshot({ path: testInfo.outputPath("responsibility-nudge.png"), animations: "disabled" });
    if (mode === "light") {
      await expect(page.getByRole("textbox", { name: "Ally job" })).toBeFocused();
    }
    await page.getByTestId("next-button").click();
    await expect(page.getByTestId("name-ally")).toBeVisible();
    await page.getByTestId("back-button").click();
    await expect(page.getByRole("textbox", { name: "Ally job" })).toHaveValue("Help me plan my day");
    await page.getByTestId("next-button").click();
    await page.getByRole("textbox", { name: "Ally name" }).fill("Mira");
    await page.getByTestId("name-ally").screenshot({ path: testInfo.outputPath("name.png"), animations: "disabled" });
    await page.getByTestId("next-button").click();
    await expect(page.getByRole("heading", { name: "How should Mira look?" })).toBeVisible();
    await page.getByTestId("color-#0d92fd").click();
    await page.getByTestId("next-button").click();
    await expect(page.getByRole("heading", { name: "What personality should Mira have?" })).toBeVisible();
    await page.getByTestId("trait-Concise").click();
    await page.getByTestId("next-button").click();
    await expect(page.getByText("Hi, I’m Mira. Let’s plan your day.", { exact: true })).toBeVisible();
    await page.getByRole("textbox", { name: "Reply to your Ally" }).fill("Help me plan tomorrow.");
    await expect(page.getByTestId("auth-allies-2")).toHaveCount(0);
    await page.getByRole("button", { name: "Send reply" }).click();
    await expect(page.locator(".waitlist-auth-card")).toHaveCSS("background-color", mode === "dark" ? "rgb(22, 22, 22)" : "rgb(255, 255, 255)");
    await page.getByTestId("signup-google").click();
    await expect(page).toHaveURL(new RegExp(`/home/${allyId}`), { timeout: 25_000 });
    await expect(page.locator("article").getByText(greeting, { exact: true })).toBeVisible();
    await expect(page.locator("article").getByText("Help me plan tomorrow.", { exact: true })).toBeVisible();
    expect(attemptBody).toMatchObject({ job: "Help me plan my day" });
    expect(attempts).toBe(1);
    expect(creations).toBe(1);
    expect(hydrationErrors).toEqual([]);
    expect(createBody).toMatchObject({ name: "Mira", onboarding_attempt: attempt, reply: "Help me plan tomorrow.", appearance: { catalog_version: "v1", key: "ghosty:0d92fd" } });
  });
}
