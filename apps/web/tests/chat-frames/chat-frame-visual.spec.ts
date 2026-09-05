import { expect, test, type Page } from "@playwright/test";

import { CHAT_FRAME_IDS } from "../../app/(debug)/chat-frames/chat-frame-fixtures";

const referenceViewport = { width: 375, height: 812 };

async function openFrame(page: Page, frameId: string) {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto(`/chat-frames?frame=${encodeURIComponent(frameId)}`, { waitUntil: "domcontentloaded" });
  await page.locator("[data-frame-ready]").waitFor();
  await page.locator("[data-frame-hydrated]").waitFor();
  await page.evaluate(async () => {
    await document.fonts.ready;
  });
}

test.describe("chat frame visual catalog", () => {
  for (const frameId of CHAT_FRAME_IDS) {
    test(`captures ${frameId}`, async ({ page, browserName }) => {
      test.skip(browserName !== "chromium", "Chromium owns the approved raster baseline.");
      await page.setViewportSize(referenceViewport);
      await openFrame(page, frameId);
      const frame = page.locator(`[data-frame-id="${frameId}"]`);
      await expect(frame).toHaveScreenshot(`chat-frame-${frameId.replace(":", "-")}.png`);
    });
  }
});

test.describe("chat frame geometry and behavior", () => {
  test("matches the reference mobile anchors", async ({ page }) => {
    await page.setViewportSize(referenceViewport);
    await openFrame(page, CHAT_FRAME_IDS[0]);
    const measurements = await page.evaluate(() => {
      const rect = (selector: string) => {
        const element = document.querySelector<HTMLElement>(selector);
        if (!element) return null;
        const box = element.getBoundingClientRect();
        return { x: box.x, y: box.y, width: box.width, height: box.height };
      };
      return {
        shell: rect("[data-testid='conversation-frame-shell']"),
        rail: rect("[data-testid='conversation-frame-rail']"),
        composer: rect("[data-testid='conversation-composer']"),
        page: { scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth },
        hitAreas: [...document.querySelectorAll<HTMLElement>("header a")]
          .filter((element) => getComputedStyle(element).display !== "none")
          .map((element) => {
            const box = element.getBoundingClientRect();
            return { width: box.width, height: box.height };
          }),
      };
    });

    expect(measurements.shell).toMatchObject({ x: 0, y: 0, width: 375, height: 812 });
    expect(measurements.rail).toMatchObject({ x: 20, width: 335 });
    expect(measurements.composer).toMatchObject({ x: 20, y: 706, width: 335, height: 48 });
    expect(measurements.page.scrollWidth).toBeLessThanOrEqual(measurements.page.clientWidth);
    expect(measurements.hitAreas.length).toBe(2);
    expect(measurements.hitAreas.every((box) => box.width >= 44 && box.height >= 44)).toBe(true);
  });

  test("reflows at the minimum mobile width without page overflow", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 700 });
    await openFrame(page, CHAT_FRAME_IDS[0]);
    const geometry = await page.evaluate(() => ({
      rail: document.querySelector<HTMLElement>("[data-testid='conversation-frame-rail']")?.getBoundingClientRect(),
      composer: document.querySelector<HTMLElement>("[data-testid='conversation-composer']")?.getBoundingClientRect(),
      documentWidth: document.documentElement.scrollWidth,
      viewportWidth: document.documentElement.clientWidth,
    }));
    expect(geometry.rail?.x).toBeCloseTo(20, 0);
    expect(geometry.rail?.width).toBeCloseTo(280, 0);
    expect(geometry.composer?.x).toBeCloseTo(20, 0);
    expect(geometry.composer?.width).toBeCloseTo(280, 0);
    expect(geometry.composer?.bottom).toBeLessThanOrEqual(700);
    expect(geometry.documentWidth).toBeLessThanOrEqual(geometry.viewportWidth);
  });

  test("toggles the native activity disclosure", async ({ page }) => {
    await openFrame(page, "315:3141");
    const details = page.locator("details");
    await expect(details).toHaveAttribute("open", "");
    await details.locator("summary").click();
    await expect(details).not.toHaveAttribute("open", "");
    await details.locator("summary").click();
    await expect(details).toHaveAttribute("open", "");
  });

  test("keeps queue removal local to the fixture", async ({ page }) => {
    await openFrame(page, "347:5953");
    await expect(page.getByRole("list", { name: "Queued messages" })).toContainText("message waiting");
    await page.getByRole("button", { name: "Remove queued message: this is a message waiting to be sent which is interesting" }).click();
    await expect(page.getByRole("button", { name: /Remove queued message:/ })).toHaveCount(0);
  });

  test("transitions report, approval, image, routine, and cart interactions", async ({ page }) => {
    await openFrame(page, "362:6356");
    await page.getByRole("button", { name: "Report" }).click();
    await expect(page.getByText("Thanks for sharing this report", { exact: true })).toBeVisible();
    await expect(page.getByText("Error message sits here")).toHaveCount(0);

    await openFrame(page, "355:6222");
    await expect(page.getByRole("dialog")).toContainText("manual approval");
    await page.getByRole("button", { name: "Approve" }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);

    await openFrame(page, "332:5289");
    await expect(page.getByRole("dialog", { name: "Image preview" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog", { name: "Image preview" })).toHaveCount(0);

    await openFrame(page, "372:6829");
    await page.getByRole("button", { name: "Delete" }).click();
    await expect(page.getByRole("dialog")).toContainText("Are you sure");
    await page.getByRole("button", { name: "Cancel" }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);

    await openFrame(page, "332:4740");
    await page.getByRole("button", { name: "Increase quantity" }).click();
    await expect(page.locator("[aria-live='polite']")).toHaveText("2");
  });
});
