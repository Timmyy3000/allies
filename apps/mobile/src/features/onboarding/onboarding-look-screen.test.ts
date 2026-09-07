import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const source = readFileSync(
  fileURLToPath(new URL('./onboarding-look-screen.tsx', import.meta.url)),
  'utf8',
);

describe('onboarding look carousel', () => {
  it('passes the Reanimated scroll handler to an Animated.ScrollView', () => {
    expect(source).toMatch(
      /<Animated\.ScrollView[\s\S]*onScroll=\{scrollHandler\}[\s\S]*<\/Animated\.ScrollView>/,
    );
  });
});
