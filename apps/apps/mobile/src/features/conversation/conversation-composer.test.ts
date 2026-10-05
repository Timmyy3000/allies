import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { getComposerBorderRadius, getComposerHeight, shouldScrollComposer } from './conversation-composer';

const layoutSource = readFileSync(fileURLToPath(new URL('./conversation-layout.tsx', import.meta.url)), 'utf8');

describe('conversation composer height', () => {
  it('keeps an empty field at the minimum height', () => {
    expect(getComposerHeight(40, false)).toBe(48);
  });
});

describe('conversation composer radius', () => {
  it('switches to the compact radius as soon as the field becomes multiline', () => {
    expect(getComposerBorderRadius(48)).toBe(100);
    expect(getComposerBorderRadius(56)).toBe(18);
    expect(getComposerBorderRadius(76)).toBe(18);
    expect(getComposerBorderRadius(96)).toBe(18);
  });
});

describe('conversation composer scrolling', () => {
  it('waits for overflowing draft content before enabling native scrolling', () => {
    expect(shouldScrollComposer('', 96)).toBe(false);
    expect(shouldScrollComposer('Hello', 48)).toBe(false);
    expect(shouldScrollComposer('Hello', 96)).toBe(true);
  });

  it('uses the send button as the only submit action so multiline return inserts a newline', () => {
    expect(layoutSource).toContain('multiline');
    expect(layoutSource).not.toContain('onSubmitEditing');
  });
});