import { expect, test, type Page } from "@playwright/test";

const workspaceId = "00000000-0000-4000-8000-000000000001";
const success = (data: unknown) => ({ status: "success", message: "ok", data });

async function mockSession(page: Page, signedIn: boolean) {
  let signInRequest: { body: unknown; csrf: string | undefined } | undefined;
  await page.route("**/api/v1/**", async (route) => {
    const headers = {
      "access-control-allow-origin": route.request().headers().origin ?? "http://127.0.0.1:3012",
      "access-control-allow-credentials": "true",
      "access-control-allow-headers": "content-type, x-csrftoken",
      "access-control-allow-methods": "GET, POST, OPTIONS",
      "access-control-expose-headers": "x-csrftoken",
    };
    if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204, headers });
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === "/api/v1/auths/csrf") {
      return route.fulfill({ status: 204, headers: { ...headers, "x-csrftoken": "a".repeat(32) } });
    }
    if (pathname === "/api/v1/auths/sign-in/google") {
      signInRequest = { body: route.request().postDataJSON(), csrf: route.request().headers()["x-csrftoken"] };
      return route.fulfill({ headers, json: success({ redirect_url: "https://accounts.example.test/sign-in" }) });
    }
    if (!signedIn) return route.fulfill({ status: 401, headers, json: { status: "error", message: "Sign in required" } });
    if (new URL(route.request().url()).pathname === "/api/v1/auths/me") {
      return route.fulfill({ headers, json: success({
        user: { id: "00000000-0000-4000-8000-000000000005" },
        profile: { display_name: "PWA tester", avatar_url: null },
        session: { id: "00000000-0000-4000-8000-000000000006", expires_at: "2099-01-02T12:00:00Z" },
        workspace: { id: workspaceId, name: "Personal", role: "owner", capabilities: [] },
      }) });
    }
    return route.fulfill({ headers, json: success({ allies: [] }) });
  });
  return { signInRequest: () => signInRequest };
}

async function offerNativeInstall(page: Page) {
  return page.evaluate(() => {
    const event = new Event("beforeinstallprompt", { cancelable: true });
    Object.assign(event, {
      prompt: async () => undefined,
      userChoice: Promise.resolve({ outcome: "dismissed", platform: "web" }),
    });
    window.dispatchEvent(event);
    return event.defaultPrevented;
  });
}

test("app entry preserves the landing and opens existing onboarding", async ({ page }, testInfo) => {
  await mockSession(page, false);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Meet your first ally" })).toBeVisible();
  await page.goto("/app");
  await expect(page.getByRole("button", { name: "Continue with Google" })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("welcome.png") });
  const start = page.getByRole("link", { name: "Make your first ally" });
  await expect(start).toHaveAttribute("href", "/onboarding");
  await start.click();
  await expect(page.getByTestId("onboarding-introduction")).toBeVisible();
});

test("welcome controls stay usable on short phones", async ({ page }, testInfo) => {
  await mockSession(page, false);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/app");
  for (const viewport of [{ width: 375, height: 812 }, { width: 375, height: 667 }, { width: 320, height: 568 }]) {
    await page.setViewportSize(viewport);
    const start = page.getByRole("link", { name: "Make your first ally" });
    const signIn = page.getByRole("button", { name: "Continue with Google" });
    await expect(start).toBeInViewport();
    await expect(signIn).toBeInViewport();
    const startBox = await start.boundingBox();
    const signInBox = await signIn.boundingBox();
    expect(startBox!.height).toBeGreaterThanOrEqual(44);
    expect(signInBox!.height).toBeGreaterThanOrEqual(44);
    expect(startBox!.y + startBox!.height).toBeLessThanOrEqual(signInBox!.y);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(viewport.width);
    await page.screenshot({ path: testInfo.outputPath(`welcome-${viewport.width}-${viewport.height}.png`) });
  }
});

test("manifest launches at app with usable icons and no service worker", async ({ page, browserName }) => {
  await mockSession(page, false);
  await page.goto("/app");
  const manifestUrl = await page.locator('link[rel="manifest"]').getAttribute("href");
  expect(manifestUrl).toBeTruthy();
  const response = await page.request.get(manifestUrl!);
  expect(response.ok()).toBe(true);
  const manifest = await response.json();
  expect(manifest).toMatchObject({ name: "allies", short_name: "allies", start_url: "/app", scope: "/", display: "standalone" });
  await expect(page.locator('meta[name="application-name"]')).toHaveAttribute("content", "allies");
  await expect(page.locator('meta[name="apple-mobile-web-app-title"]')).toHaveAttribute("content", "allies");
  for (const icon of manifest.icons) {
    const image = await page.request.get(icon.src);
    expect(image.ok()).toBe(true);
    expect(image.headers()["content-type"]).toContain("image/png");
  }
  expect(await page.evaluate(async () => (await navigator.serviceWorker.getRegistrations()).length)).toBe(0);
  if (browserName === "chromium") {
    const cdp = await page.context().newCDPSession(page);
    const result = await cdp.send("Page.getAppManifest");
    expect(result.errors).toEqual([]);
    await expect.poll(async () => (await cdp.send("Page.getInstallabilityErrors")).installabilityErrors).toEqual([]);
    await cdp.detach();
  }
});

test("Google action uses the existing secure sign-in contract", async ({ page }) => {
  const cloud = await mockSession(page, false);
  await page.route("https://accounts.example.test/sign-in", (route) => route.fulfill({ contentType: "text/html", body: "<h1>Provider handoff</h1>" }));
  await page.goto("/app");
  await page.getByRole("button", { name: "Continue with Google" }).click();
  await expect(page).toHaveURL("https://accounts.example.test/sign-in");
  expect(cloud.signInRequest()).toEqual({ body: { redirect_to: "/home" }, csrf: "a".repeat(32) });
});

test("signed-in launch reaches Home and remembers an install dismissal", async ({ page }, testInfo) => {
  await mockSession(page, true);
  await page.goto("/app");
  await expect(page).toHaveURL(/\/home$/);
  await expect(page.getByRole("link", { name: "PWA tester" })).toBeVisible();
  expect(await offerNativeInstall(page)).toBe(true);
  await expect(page.getByRole("button", { name: "Install Allies", exact: true })).toBeVisible({ timeout: 10_000 });
  await page.getByRole("link", { name: "PWA tester" }).click({ trial: true });
  await page.getByRole("button", { name: /^Make an ally$/i }).click({ trial: true });
  await page.screenshot({ path: testInfo.outputPath("install-invitation.png") });
  await page.getByRole("button", { name: "Not now", exact: true }).click();
  await expect(page.getByRole("button", { name: "Install Allies", exact: true })).toBeHidden();
  await page.reload();
  await expect(page.getByRole("link", { name: "PWA tester" })).toBeVisible();
  await offerNativeInstall(page);
  await page.waitForTimeout(3500);
  await expect(page.getByRole("button", { name: "Install Allies", exact: true })).toBeHidden();
});

test("iOS installation explains the manual steps", async ({ page }, testInfo) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "userAgent", { value: "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1" });
    Object.defineProperty(navigator, "standalone", { value: false });
  });
  await mockSession(page, true);
  await page.goto("/home");
  const install = page.getByRole("button", { name: "Install Allies", exact: true });
  await expect(install).toBeVisible({ timeout: 10_000 });
  await install.click();
  await expect(page.getByText(/Add to Home Screen/)).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("ios-instructions.png") });
});

test("standalone launch suppresses installation", async ({ page }) => {
  await page.addInitScript(() => Object.defineProperty(navigator, "standalone", { value: true }));
  await mockSession(page, true);
  await page.goto("/app");
  await expect(page).toHaveURL(/\/home$/);
  await expect(page.getByRole("link", { name: "PWA tester" })).toBeVisible();
  await offerNativeInstall(page);
  await page.waitForTimeout(3500);
  await expect(page.getByRole("button", { name: "Install Allies", exact: true })).toBeHidden();
});
