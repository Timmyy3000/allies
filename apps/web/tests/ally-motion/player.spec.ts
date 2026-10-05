import { expect, test } from '@playwright/test';
import { createAllyDocument } from '@allies/ally-motion';

for (const shape of ['boxy', 'ghosty', 'rocky', 'rolly'] as const) {
  test(`${shape} preserves wake pose, morphs eyes, and returns to neutral idle`, async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.clock.install({ time: new Date(0) });
    await page.clock.pauseAt(new Date(1000));
    await page.setContent(createAllyDocument(shape, { state: 'sleeping', reduced: false }));
    await page.clock.runFor(1730);
    const head = page.locator('#head');
    const matrix = () => head.evaluate(node => {
      const m = (node as SVGGraphicsElement).getCTM()!;
      return [m.a, m.b, m.c, m.d, m.e, m.f];
    });
    const before = await matrix();
    await page.evaluate(() => {
      (window as unknown as { setAllyPlayback: (value: object) => void }).setAllyPlayback({ state: 'idle', reduced: false });
    });
    const after = await matrix();
    before.forEach((value, i) => expect(after[i]).toBeCloseTo(value, 3));
    await expect(page.locator('body')).toHaveAttribute('data-state', 'waking');
    const eye = page.locator('#eye_l > path');
    const closed = await eye.evaluate(node => (node as SVGGraphicsElement).getBBox().height);
    await page.clock.runFor(1050);
    const opening = await eye.evaluate(node => (node as SVGGraphicsElement).getBBox().height);
    expect(opening).not.toBe(closed);
    await page.clock.runFor(850);
    await expect(page.locator('body')).toHaveAttribute('data-state', 'idle');
    expect(await eye.evaluate(node => (node as SVGGraphicsElement).getBBox().height)).not.toBe(opening);
    expect(errors).toEqual([]);
  });
}

test('sleep Zs keep moving and reduced motion stops the timeline', async ({ page }) => {
  await page.clock.install({ time: new Date(0) });
  await page.clock.pauseAt(new Date(1000));
  await page.setContent(createAllyDocument('rolly', { state: 'sleeping', reduced: false }));
  const z = page.locator('.sleep-z').first();
  let previous = '';
  for (let sample = 0; sample < 12; sample++) {
    await page.clock.runFor(300);
    const transform = await z.evaluate(node => getComputedStyle(node).transform);
    expect(transform).not.toBe(previous);
    previous = transform;
  }
  await page.evaluate(() => {
    (window as unknown as { setAllyPlayback: (value: object) => void }).setAllyPlayback({ state: 'sleeping', reduced: true });
  });
  const before = await z.evaluate(node => getComputedStyle(node).transform);
  await page.clock.runFor(5000);
  expect(await z.evaluate(node => getComputedStyle(node).transform)).toBe(before);
});
