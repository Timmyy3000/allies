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
    await expect(page.getByTestId("conversation-frame-scroll-blur")).toBeHidden();
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

  test("keeps focused mobile input readable without zoom-sized text or overflow", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await openFrame(page, CHAT_FRAME_IDS[0]);
    const input = page.locator("#ally-message");
    await input.fill("A reply\nwith another line");
    await input.focus();
    const geometry = await input.evaluate((element) => ({
      fontSize: parseFloat(getComputedStyle(element).fontSize),
      left: element.getBoundingClientRect().left,
      right: element.getBoundingClientRect().right,
      viewportWidth: document.documentElement.clientWidth,
      pageWidth: document.documentElement.scrollWidth,
    }));
    expect(geometry.fontSize).toBeGreaterThanOrEqual(16);
    expect(geometry.left).toBeGreaterThanOrEqual(0);
    expect(geometry.right).toBeLessThanOrEqual(geometry.viewportWidth);
    expect(geometry.pageWidth).toBeLessThanOrEqual(geometry.viewportWidth);
  });

  test("keeps long mobile bubbles compact", async ({ page }) => {
    await page.setViewportSize(referenceViewport);
    await openFrame(page, "315:3009");
    const geometry = await page.evaluate(() => {
      const bubble = document.querySelector<HTMLElement>("article[data-multiline='true']")!;
      const rail = document.querySelector<HTMLElement>("[data-testid='conversation-frame-rail']")!;
      return {
        bubbleWidth: bubble.getBoundingClientRect().width,
        railWidth: rail.getBoundingClientRect().width,
      };
    });

    expect(geometry.bubbleWidth).toBeLessThanOrEqual(255);
    expect(geometry.bubbleWidth / geometry.railWidth).toBeLessThanOrEqual(0.77);

    const productionGeometry = await page.evaluate(() => {
      const rules = [...document.styleSheets].flatMap((sheet) => {
        try { return [...sheet.cssRules]; } catch { return []; }
      });
      const productionRule = rules.find((rule): rule is CSSStyleRule => (
        rule instanceof CSSStyleRule
        && rule.style.getPropertyValue("--chat-history-clearance").includes("136px")
      ));
      const productionClass = productionRule?.selectorText.match(/\.([\w-]*frameProduction[\w-]*)/)?.[1];
      const shell = document.querySelector<HTMLElement>("[data-testid='conversation-frame-shell']")!;
      const canvas = document.querySelector<HTMLElement>("[data-testid='conversation-frame-canvas']")!;
      const blur = document.querySelector<HTMLElement>("[data-testid='conversation-frame-scroll-blur']")!;
      if (productionClass) shell.classList.add(productionClass);
      return {
        productionClass,
        canvasTop: parseFloat(getComputedStyle(canvas).paddingTop),
        gradientHeight: parseFloat(getComputedStyle(blur).height),
      };
    });
    expect(productionGeometry.productionClass).toBeTruthy();
    expect(productionGeometry.canvasTop - productionGeometry.gradientHeight).toBeCloseTo(4, 0);
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

  test("bounds an unbroken queued URL without hiding its controls", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 700 });
    await openFrame(page, "347:5953");
    const queue = page.getByRole("list", { name: "Queued messages" });
    await queue.locator("li > span").first().evaluate((element) => {
      element.textContent = `https://example.com/${"unbroken".repeat(80)}`;
    });
    const geometry = await queue.locator("li").evaluate((item) => {
      const bounds = item.getBoundingClientRect();
      const parent = item.parentElement!.getBoundingClientRect();
      const buttons = [...item.querySelectorAll("button")].map((button) => {
        const box = button.getBoundingClientRect();
        return { left: box.left, right: box.right, width: box.width };
      });
      return { left: bounds.left, right: bounds.right, parentLeft: parent.left, parentRight: parent.right, buttons };
    });

    expect(geometry.left).toBeGreaterThanOrEqual(geometry.parentLeft);
    expect(geometry.right).toBeLessThanOrEqual(geometry.parentRight);
    expect(geometry.buttons.length).toBe(2);
    expect(geometry.buttons.every((button) => button.width > 0 && button.left >= geometry.left && button.right <= geometry.right)).toBe(true);
  });

});
