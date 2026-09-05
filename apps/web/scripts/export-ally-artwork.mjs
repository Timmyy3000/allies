import { chromium } from 'playwright';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { normalizePathMotion } from '../../../packages/ally-motion/scripts/svg-path-motion.mjs';

const root = new URL('../../../', import.meta.url);
const player = await readFile(new URL('packages/ally-motion/src/player.js', root), 'utf8');
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 470, height: 470 } });
  for (const shape of ['boxy', 'ghosty', 'rocky', 'rolly']) {
    const assets = {};
    for (const state of ['idle', 'thinking', 'sleeping', 'waking', 'falling-asleep']) {
      assets[state] = normalizePathMotion(await readFile(new URL(`packages/ally-motion/artwork/${state}_${shape}.svg`, root), 'utf8'), state);
      if (state === 'waking' || state === 'falling-asleep') continue;
      const folder = new URL(`apps/web/public/ally/${state}/`, root);
      await mkdir(folder, { recursive: true });
      await writeFile(new URL(`${state}_${shape}.svg`, folder), assets[state]);
    }
    for (const state of ['idle', 'thinking', 'sleeping']) {
      const config = JSON.stringify({ assets, state, reduced: true }).replace(/</g, '\\u003c');
      await page.setContent(`<body><script>${player}\nstartAlly(${config})</script></body>`);
      const svg = await page.locator('svg').evaluate(root => {
        const properties = ['opacity', 'visibility', 'display', 'fill', 'fill-rule', 'stroke', 'stroke-width', 'stroke-linecap', 'stroke-linejoin', 'stroke-dasharray', 'stroke-dashoffset', 'mask-type'];
        const samples = [...root.querySelectorAll('*')].filter(node => node.tagName !== 'style').map(node => {
          const css = getComputedStyle(node);
          const attributes = properties.map(key => [key, css.getPropertyValue(key)]);
          const path = css.getPropertyValue('d').match(/^path\(["'](.*)["']\)$/);
          if (path) attributes.push(['d', path[1]]);
          if (css.transform !== 'none') {
            const [x, y] = css.transformOrigin.split(' ').map(parseFloat);
            const transform = new DOMMatrix().translate(x || 0, y || 0).multiply(new DOMMatrix(css.transform)).translate(-x || 0, -y || 0);
            attributes.push(['transform', transform.toString()]);
          }
          return [node, attributes];
        });
        samples.forEach(([node, attributes]) => {
          node.removeAttribute('style');
          attributes.forEach(([key, value]) => { if (value) node.setAttribute(key, value); });
        });
        root.querySelectorAll('style').forEach(node => node.remove());
        root.querySelectorAll('animate').forEach(node => node.remove());
        return root.outerHTML;
      });
      await writeFile(new URL(`apps/web/public/ally/${state}/${state}_${shape}.reduced.svg`, root), svg);
    }
  }
} finally {
  await browser.close();
}
