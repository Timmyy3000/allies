import { expect, test } from "@playwright/test";

test("Meet your first ally opens the name step", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  const cta = page.getByTestId("make-first-ally").filter({ visible: true });
  await expect(cta).toBeVisible();
  await expect(cta).toBeEnabled();
  await cta.click({ force: true });
  await expect(page).toHaveURL("/");
  await expect(page.getByTestId("onboarding-drawer")).toBeVisible();
  await expect(page.getByTestId("onboarding-drawer")).toHaveAttribute("data-page-overlay", "true");
  await expect(page.getByTestId("name-ally")).toBeVisible();
  await expect(page.getByTestId("ally-name-input")).toBeVisible();
});

test("desktop Meet your first ally opens the name step", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  await page.getByTestId("make-first-ally").filter({ visible: true }).click({ force: true });
  await expect(page.getByTestId("name-ally")).toBeVisible();
});
