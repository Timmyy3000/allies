import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const editorSources = [
  readFileSync(fileURLToPath(new URL('./onboarding-job-screen.tsx', import.meta.url)), 'utf8'),
  readFileSync(fileURLToPath(new URL('./onboarding-personality-screen.tsx', import.meta.url)), 'utf8'),
];

describe('onboarding editor cards', () => {
  it('lets both keyboard-sized editors fill and scroll inside the compact card', () => {
    for (const source of editorSources) {
      expect(source).toContain('flex: 1');
      expect(source).not.toContain('minHeight: 250');
      expect(source).toContain('scrollEnabled');
    }
  });
});
