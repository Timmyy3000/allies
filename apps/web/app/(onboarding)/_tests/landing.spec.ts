import { expect, test } from "@playwright/test";

test("Meet your first ally opens the introduction", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  const cta = page.getByTestId("make-first-ally").filter({ visible: true });
  await expect(cta).toBeVisible();
  await expect(cta).toBeEnabled();
  await cta.click({ force: true });
  await expect(page).toHaveURL("/");
  await expect(page.getByTestId("onboarding-drawer")).toBeVisible();
  await expect(page.getByTestId("onboarding-drawer")).toHaveAttribute("data-page-overlay", "true");
  await expect(page.getByTestId("onboarding-introduction")).toBeVisible();
  await page.getByTestId("next-button").click();
  await expect(page.getByTestId("job-input")).toBeVisible();
  await page.getByTestId("back-button").click();
  await expect(page.getByTestId("onboarding-introduction")).toBeVisible();
  await page.getByTestId("back-button").click();
  await expect(page.getByTestId("onboarding-drawer")).toHaveCount(0);
});

test("desktop Meet your first ally opens the introduction", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  await page.getByTestId("make-first-ally").filter({ visible: true }).click({ force: true });
  await expect(page.getByTestId("onboarding-introduction")).toBeVisible();
});

test("intro Allies wander naturally and stay still with reduced motion", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.goto("/");
  await page.getByRole("button", { name: "Skip story animation" }).click();
  await page.getByTestId("make-first-ally").filter({ visible: true }).click();
  const actors = page.locator(".onboarding-intro-scene [data-wander]");
  await expect(actors).toHaveCount(4);
  const positions = () => actors.evaluateAll((nodes) => nodes.map((node) => (node as HTMLElement).style.transform));
  const initial = await positions();
  await expect.poll(positions).not.toEqual(initial);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.reload();
  await page.getByTestId("make-first-ally").filter({ visible: true }).click();
  await expect(actors).toHaveCount(4);
  const reduced = await positions();
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  expect(await positions()).toEqual(reduced);
});
