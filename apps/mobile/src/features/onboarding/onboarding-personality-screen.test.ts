import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const source = readFileSync(
  fileURLToPath(new URL('./onboarding-personality-screen.tsx', import.meta.url)),
  'utf8',
);

describe('personality selector layout', () => {
  it('gives the vertical viewport room for the horizontal selector to reach both edges', () => {
    const rootScrollViewStart = source.indexOf('<ScrollView');
    const rootScrollViewEnd = source.indexOf('>', rootScrollViewStart);

    expect(source.slice(rootScrollViewStart, rootScrollViewEnd)).toContain(
      'style={[styles.root, { backgroundColor: theme.appBackground }, edgeToEdgeStyle]}',
    );
    expect(source).toContain('paddingHorizontal: ONBOARDING_PERSONALITY_ROW_INSET');
  });

  it('moves the selector below the compact editor with the same keyboard progress', () => {
    expect(source).toContain('<Animated.ScrollView');
    expect(source).toContain('personalitySelectorStyle');
    expect(source).toContain('getOnboardingPersonalitySelectorOffset(keyboardProgress.value)');
    expect(source).not.toContain('editorLift');
    expect(source).toContain('pointerEvents="box-none"');
  });

  it('uses the shared account-sheet close icon in personality help', () => {
    expect(source).toContain("source={require('@/assets/allies/icons/x-icon.svg')}");
    expect(source).not.toContain('>×</Text>');
  });
});
