import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const source = readFileSync(
  fileURLToPath(new URL('./theme.ts', import.meta.url)),
  'utf8',
);
const darkThemeSource = source.slice(source.indexOf('dark: {'));

describe('mobile theme contract', () => {
  it('keeps the approved dark palette', () => {
    const darkTokens = {
      background: '#000000',
      appBackground: '#000000',
      buttonText: '#FFFFFF',
      chatInput: '#121212',
      controlSurface: '#161616',
      icon: '#FFFFFF',
      inactiveButton: '#202020',
      modalCancelIcon: '#121212',
      modalCancelSurface: '#FFFFFF',
      modalSurface: '#161616',
      neutralButtonSurface: '#202020',
      neutralButtonText: '#757575',
      onboardingInput: '#161616',
      onboardingInputFocused: '#161616',
      placeholderText: '#606060',
      primaryText: '#FFFFFF',
      progressTrack: '#202020',
      shimmerHighlight: '#B8B8B8',
      supportingText: '#757575',
      disabledButtonText: '#757575',
      errorText: '#FF8A80',
    };

    for (const [key, value] of Object.entries(darkTokens)) {
      expect(darkThemeSource).toContain(`${key}: '${value}'`);
    }
  });

  it('uses light for every non-dark device scheme', () => {
    expect(source).toContain("return scheme === 'dark' ? Colors.dark : Colors.light;");
  });
});
