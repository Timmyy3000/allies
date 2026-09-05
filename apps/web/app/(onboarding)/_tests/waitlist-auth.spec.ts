import { expect, test, type Page } from "@playwright/test";

const ALLY_NAME = "Tolani";

async function fillField(page: Page, testId: string, value: string) {
  const field = page.getByTestId(testId);
  await field.click();
  await field.pressSequentially(value, { delay: 15 });
}

async function continueWhenReady(page: Page) {
  await expect(page.getByTestId("next-button")).toBeEnabled();
  await page.getByTestId("next-button").click();
}

async function reachWaitlistPreview(page: Page) {
  await page.goto("/onboarding");
  await expect(page.getByTestId("name-ally")).toBeVisible();
  await fillField(page, "ally-name-input", ALLY_NAME);
  await continueWhenReady(page);

  await expect(page.getByTestId("look-like")).toBeVisible();
  await page.getByTestId("color-#fd304f").click();
  await continueWhenReady(page);

  await expect(page.getByTestId("job-description")).toBeVisible();
  await fillField(page, "job-input", "Help me plan the week");
  await continueWhenReady(page);

  await expect(page.getByTestId("personality-page")).toBeVisible();
  await page.getByTestId("trait-Concise").click();
  await continueWhenReady(page);

  await expect(page.getByTestId("coming-alive")).toBeVisible();
  await expect(page.getByTestId("waitlist-reply")).toBeVisible({ timeout: 12_000 });
  await expect(page.getByTestId("thinking-status")).toBeHidden({ timeout: 8_000 });
}

async function expectAuthOverlay(page: Page) {
  const overlay = page.getByTestId("auth-allies-2");
  await expect(overlay).toBeVisible();
  await expect(overlay.getByRole("heading", { name: /Create your/ })).toBeVisible();
  await expect(
    overlay.getByText(
      "Your ally has been saved but you need to set up an account to use it.",
    ),
  ).toBeVisible();
  await expect(page.getByTestId("signup-chatgpt")).toHaveText("Sign up with ChatGPT");
  await expect(page.getByTestId("signup-google")).toHaveText("Sign up with Google");
}

test.describe("waitlist auth gate", () => {
  test.setTimeout(60_000);

  test("opens the account overlay, then later leaves for Home", async ({
    page,
  }) => {
    await reachWaitlistPreview(page);
    await page.getByTestId("waitlist-reply").click();
    await expectAuthOverlay(page);

    await page.getByTestId("auth-overlay-close").click();
    await expect(page.getByTestId("auth-allies-2")).toHaveCount(0);

    await page.getByTestId("waitlist-reply").click();
    await expectAuthOverlay(page);

    await page.getByTestId("signup-chatgpt").click();
    await expect(page.getByTestId("welcome-allies-1")).toBeVisible();
    await expect(page.getByRole("heading", { name: `Looking good, ${ALLY_NAME}` })).toBeVisible();
    await expect(page.getByText("We’re done with the basics, one more thing")).toBeVisible();

    await expect(page.getByTestId("allow-notifications-allies")).toBeVisible({
      timeout: 6_000,
    });
    await expect(page.getByRole("heading", { name: "Keep up with your allies" })).toBeVisible();
    await page.getByTestId("notifications-later").click();

    await expect(page).toHaveURL(/\/(home|sign-in)/);
  });

  test("desktop overlay sits 24px from the bottom", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await reachWaitlistPreview(page);
    await page.getByTestId("waitlist-reply").click();
    await expectAuthOverlay(page);

    const card = page.locator(".waitlist-auth-card");
    await expect(card).toBeVisible();
    const box = await card.boundingBox();
    expect(box).not.toBeNull();
    if (box) {
      const viewport = page.viewportSize();
      expect(viewport).not.toBeNull();
      if (viewport) {
        const gap = viewport.height - (box.y + box.height);
        expect(gap).toBeGreaterThanOrEqual(22);
        expect(gap).toBeLessThanOrEqual(28);
      }
      expect(box.width).toBeGreaterThan(300);
    }
  });
});
