import { JSDOM } from 'jsdom';
import { afterEach, describe, expect, test } from 'vitest';
import { readFileSync } from 'node:fs';
import { createAllyDocument } from './index';

const runtime = readFileSync(new URL('./player.js', import.meta.url), 'utf8');
const windows: JSDOM[] = [];

function player(initial = 'idle', reduced = false, phase = 0) {
  const dom = new JSDOM('<body></body>', { runScripts: 'outside-only', pretendToBeVisual: true });
  windows.push(dom);
  const window = dom.window;
  let callback: ((now: number) => void) | undefined;
  let now = 100;
  let time = 0;
  window.Math.random = () => phase;
  Object.assign(window.Element.prototype, { setCurrentTime(value: number) { time = value; } });
  window.requestAnimationFrame = cb => { callback = cb; return 1; };
  window.cancelAnimationFrame = () => { callback = undefined; };
  window.document.getAnimations = () => [];
  window.Element.prototype.animate = () => ({ pause() {}, cancel() {}, currentTime: 0 }) as unknown as Animation;
  window.eval(runtime);
  const assets = Object.fromEntries(['idle', 'thinking', 'sleeping', 'waking', 'falling-asleep'].map(state => [state, '<svg xmlns="http://www.w3.org/2000/svg"></svg>']));
  window.eval(`startAlly(${JSON.stringify({ assets, state: initial, reduced })})`);
  return {
    time: () => time,
    state: () => window.document.body.dataset.state,
    svg: () => window.document.querySelector('svg'),
    running: () => Boolean(callback),
    request(state: string, reduced = false, paused = false, skipWakeTransition = false) { window.eval(`setAllyPlayback(${JSON.stringify({ state, reduced, paused, skipWakeTransition })})`); },
    run(ms: number) {
      for (let i = 0; i <= ms; i += 10) { now += 10; const next = callback; callback = undefined; next?.(now); }
    },
  };
}

afterEach(() => { windows.splice(0).forEach(dom => dom.window.close()); });

describe('approved Ally playback lifecycle', () => {
  test('starts asleep immediately at independent loop phases', () => {
    const first = player('sleeping', false, 0.2);
    const second = player('sleeping', false, 0.7);
    expect(first.state()).toBe('sleeping');
    expect(first.time()).toBeCloseTo(1.92);
    expect(second.time()).toBeCloseTo(6.72);
    expect(player('sleeping', true, 0.7).time()).toBe(0);
  });
  test('finishes an awake loop, falls asleep once, then loops sleeping', () => {
    const p = player();
    p.run(1000); p.request('sleeping'); p.run(2900);
    expect(p.state()).toBe('idle');
    p.run(120); expect(p.state()).toBe('falling-asleep');
    p.run(1420); expect(p.state()).toBe('sleeping');
    const svg = p.svg(); p.run(20000); expect(p.svg()).toBe(svg);
  });
  test('wakes promptly at an arbitrary sleep phase and reaches latest awake state', () => {
    const p = player('sleeping'); p.run(1900); p.request('idle');
    expect(p.state()).toBe('waking');
    p.request('thinking'); p.run(1850); expect(p.state()).toBe('thinking');
  });
  test('can use idle motion immediately while the conversation waits for readiness', () => {
    const p = player('sleeping');
    p.request('idle', false, false, true);
    expect(p.state()).toBe('idle');
    p.run(2000);
    expect(p.state()).toBe('idle');
    expect(p.running()).toBe(true);
  });
  test('latest request cancels a pending sleep without restarting idle', () => {
    const p = player(); const svg = p.svg();
    p.request('sleeping'); p.run(1200); p.request('idle'); p.run(5000);
    expect(p.svg()).toBe(svg);
  });
  test('a reversal during falling asleep completes its endpoint then wakes', () => {
    const p = player(); p.request('sleeping'); p.run(4200);
    expect(p.state()).toBe('falling-asleep');
    p.request('thinking'); p.run(1250); expect(p.state()).toBe('waking');
    p.run(1450); expect(p.state()).toBe('thinking');
  });
  test('reduced motion immediately resolves transitions and has no frame loop', () => {
    const p = player('sleeping'); p.request('idle'); p.request('thinking', true);
    expect(p.state()).toBe('thinking'); expect(p.running()).toBe(false);
    p.request('sleeping', true); expect(p.state()).toBe('sleeping');
    p.request('sleeping'); expect(p.running()).toBe(true);
  });
  test('background suspension preserves the current document and resumes', () => {
    const p = player('thinking'); p.run(1500); const svg = p.svg();
    p.request('thinking', false, true); expect(p.running()).toBe(false);
    p.run(20000); p.request('thinking'); p.run(100);
    expect(p.svg()).toBe(svg); expect(p.running()).toBe(true);
  });
  test('bundles local approved art without external resource or navigation privileges', () => {
    for (const shape of ['boxy', 'ghosty', 'rocky', 'rolly'] as const) {
      const html = createAllyDocument(shape, { state: 'sleeping', reduced: false });
      expect(html).toContain("default-src 'none'");
      expect(html).toContain('brow-thickness');
      expect(html).toContain('cutout-l');
      expect(html).not.toMatch(/https?:\/\/(?!www\.w3\.org)/);
    }
  });
});
