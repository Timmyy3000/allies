import { expect, test } from "@playwright/test";
const id = (n: number) => `00000000-0000-4000-8000-${n.toString().padStart(12, "0")}`;
const material = { endpoint: "https://fcm.googleapis.com/browser-test", keys: { p256dh: "B".repeat(87), auth: "A".repeat(22) } };
test("Preferences grant/deny and real worker binding/clear stay consistent", async ({ page, context }) => {
  test.setTimeout(90000);
  await context.grantPermissions(["notifications"]);
  await page.addInitScript(material => {
    Object.defineProperty(Notification, "permission", { configurable: true, value: "granted" });
    Object.defineProperty(PushManager.prototype, "getSubscription", { value: async () => ({ toJSON: () => material }) });
  }, material);
  await page.route("**/api/v1/**", async route => {
    const request = route.request(); const path = new URL(request.url()).pathname;
    const headers = { "access-control-allow-origin": request.headers().origin ?? "http://127.0.0.1:3010", "access-control-allow-credentials": "true", "access-control-allow-headers": "content-type, x-csrftoken", "access-control-allow-methods": "GET, POST, DELETE, OPTIONS", "access-control-expose-headers": "x-csrftoken" };
    if (request.method() === "OPTIONS") return route.fulfill({ status: 204, headers });
    if (path.endsWith("/csrf")) return route.fulfill({ status: 204, headers: { ...headers, "x-csrftoken": "a".repeat(32) } });
    if (request.method() === "DELETE") return route.fulfill({ status: 204, headers });
    let data: unknown = [];
    if (path.endsWith("/auths/me")) data = { user: { id: id(1) }, profile: { display_name: "Browser Test", avatar_url: null }, session: { id: id(2), expires_at: "2099-01-01T00:00:00Z" }, workspace: { id: id(3), name: "Test", role: "owner", capabilities: [] } };
    if (path.endsWith("/push/config")) data = { enabled: true, vapid_public_key: "B".repeat(87), presence_ttl_seconds: 60, heartbeat_seconds: 20 };
    if (path.endsWith("/push/subscriptions")) { const input = request.postDataJSON(); data = { subscription_id: id(5), browser_id: input.browser_id, binding_id: input.binding_id, workspace_id: id(3), session_id: id(2), state: "active" }; }
    if (path.endsWith("/presence")) data = { accepted_sequence: request.postDataJSON().sequence, foreground_until: null };
    if (/integrations\/[^/]+\/connection$/.test(path)) data = null;
    await route.fulfill({ headers, json: { status: "success", message: "OK", data } });
  });
  await page.goto("/account");
  await context.grantPermissions(["notifications"], { origin: new URL(page.url()).origin });
  const toggle = page.getByRole("switch", { name: "Notifications" });
  await expect(toggle).toBeEnabled(); await expect(toggle).toHaveAttribute("aria-checked", "false");
  expect(await page.evaluate(() => Notification.permission)).toBe("granted");
  await toggle.click(); await expect(toggle).toHaveAttribute("aria-checked", "true");
  const bound = await page.evaluate(async () => {
    const registration = await navigator.serviceWorker.ready; const channel = new MessageChannel();
    const reply = new Promise<Record<string, unknown>>(resolve => { channel.port1.onmessage = event => resolve(event.data); });
    registration.active!.postMessage({ type: "PUSH_STATE" }, [channel.port2]); return reply;
  });
  expect(bound.binding).toMatchObject({ owner_user_id: id(1), session_id: id(2), workspace_id: id(3) });
  const worker = context.serviceWorkers().find(worker => worker.url().endsWith("/sw.js"));
  expect(worker).toBeTruthy();
  const payload = { version: 1, notification_id: id(8), binding_id: (bound.binding as { binding_id: string }).binding_id, kind: "reply_completed", workspace_id: id(3), ally_id: id(7), conversation_id: id(9), expires_at: new Date(Date.now() + 60000).toISOString() };
  await worker!.evaluate('self.__notices = []; Object.defineProperty(self.registration, "getNotifications", {value: async () => self.__notices.slice()}); Object.defineProperty(self.registration, "showNotification", {value: async (title, options) => { const notice = {data: options.data, close() { self.__notices = self.__notices.filter(item => item !== notice); }}; self.__notices.push(notice); }});');
  await worker!.evaluate(`(async () => { const payload = ${JSON.stringify(payload)}; const event = new Event("push"); event.data = {text: () => JSON.stringify(payload), json: () => payload}; let done; event.waitUntil = promise => {done = promise}; self.dispatchEvent(event); await done; })()`);
  await expect.poll(() => worker!.evaluate("self.registration.getNotifications().then(notifications => notifications.length)")).toBe(1);
  await worker!.evaluate('(async () => { const notifications = await self.registration.getNotifications(); const event = new Event("notificationclick"); event.notification = notifications[0]; let done; event.waitUntil = promise => {done = promise}; self.dispatchEvent(event); await done; })()');
  await expect(page).toHaveURL(new RegExp(`/home/${id(7)}\\?push_workspace=${id(3)}&push_conversation=${id(9)}`));
  await page.goto("/account"); await expect(toggle).toHaveAttribute("aria-checked", "true");
  await toggle.click(); await expect(toggle).toHaveAttribute("aria-checked", "false");
  await page.evaluate(() => { Object.defineProperty(Notification, "permission", { configurable: true, value: "default" }); Notification.requestPermission = async () => "denied"; });
  await toggle.click(); await expect(page.getByText("Allow notifications in your browser settings, then try again.")).toBeVisible();
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  const response = await page.request.get("/sw.js"); expect(response.headers()["cache-control"]).toContain("no-store");
});
