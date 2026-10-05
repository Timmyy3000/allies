/**
 * Below are the colors that are used in the app. The colors are defined in the light and dark mode.
 * There are many other ways to style your app. For example, [Nativewind](https://www.nativewind.dev/), [Tamagui](https://tamagui.dev/), [unistyles](https://reactnativeunistyles.vercel.app), etc.
 */

import '@/global.css';

import { Platform, type ColorSchemeName } from 'react-native';

export type Theme = {
  text: string;
  background: string;
  backgroundElement: string;
  backgroundSelected: string;
  textSecondary: string;
  appBackground: string;
  primaryText: string;
  buttonText: string;
  neutralButtonSurface: string;
  neutralButtonText: string;
  disabledButtonText: string;
  placeholderText: string;
  supportingText: string;
  controlSurface: string;
  onboardingInput: string;
  onboardingInputFocused: string;
  chatInput: string;
  modalSurface: string;
  inactiveButton: string;
  progressTrack: string;
  shimmerHighlight: string;
  errorText: string;
  icon: string;
  modalCancelSurface: string;
  modalCancelIcon: string;
};

export const Colors = {
  light: {
    text: '#000000',
    background: '#ffffff',
    backgroundElement: '#F0F0F3',
    backgroundSelected: '#E0E1E6',
    textSecondary: '#60646C',
    appBackground: '#FFFFFF',
    primaryText: '#121212',
    buttonText: '#FFFFFF',
    neutralButtonSurface: '#F3F3F3',
    neutralButtonText: '#121212',
    disabledButtonText: '#FFFFFF',
    placeholderText: '#D9D9D9',
    supportingText: '#757575',
    controlSurface: '#F3F3F3',
    onboardingInput: '#F3F3F3',
    onboardingInputFocused: '#F1F1F1',
    chatInput: '#F3F3F3',
    modalSurface: '#FFFFFF',
    inactiveButton: '#D9D9D9',
    progressTrack: '#F3F3F3',
    shimmerHighlight: '#FFFFFF',
    errorText: '#B42318',
    icon: '#121212',
    modalCancelSurface: '#121212',
    modalCancelIcon: '#FFFFFF',
  },
  dark: {
    text: '#ffffff',
    background: '#000000',
    backgroundElement: '#212225',
    backgroundSelected: '#2E3135',
    textSecondary: '#B0B4BA',
    appBackground: '#000000',
    primaryText: '#FFFFFF',
    buttonText: '#FFFFFF',
    neutralButtonSurface: '#202020',
    neutralButtonText: '#757575',
    disabledButtonText: '#757575',
    placeholderText: '#606060',
    supportingText: '#757575',
    controlSurface: '#161616',
    onboardingInput: '#161616',
    onboardingInputFocused: '#161616',
    chatInput: '#121212',
    modalSurface: '#161616',
    inactiveButton: '#202020',
    progressTrack: '#202020',
    shimmerHighlight: '#B8B8B8',
    errorText: '#FF8A80',
    icon: '#FFFFFF',
    modalCancelSurface: '#FFFFFF',
    modalCancelIcon: '#121212',
  },
} as const;

export function getTheme(scheme: ColorSchemeName | null | undefined): Theme {
  return scheme === 'dark' ? Colors.dark : Colors.light;
}

export type ThemeColor = keyof typeof Colors.light & keyof typeof Colors.dark;

export const Fonts = Platform.select({
  ios: {
    /** iOS `UIFontDescriptorSystemDesignDefault` */
    sans: 'system-ui',
    /** iOS `UIFontDescriptorSystemDesignSerif` */
    serif: 'ui-serif',
    /** iOS `UIFontDescriptorSystemDesignRounded` */
    rounded: 'ui-rounded',
    /** iOS `UIFontDescriptorSystemDesignMonospaced` */
    mono: 'ui-monospace',
  },
  default: {
    sans: 'normal',
    serif: 'serif',
    rounded: 'normal',
    mono: 'monospace',
  },
  web: {
    sans: 'var(--font-display)',
    serif: 'var(--font-serif)',
    rounded: 'var(--font-rounded)',
    mono: 'var(--font-mono)',
  },
});

export const Spacing = {
  half: 2,
  one: 4,
  two: 8,
  three: 16,
  four: 24,
  five: 32,
  six: 64,
} as const;

export const BottomTabInset = Platform.select({ ios: 50, android: 80 }) ?? 0;
export const MaxContentWidth = 800;
