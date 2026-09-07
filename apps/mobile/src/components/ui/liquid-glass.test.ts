import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import { getLiquidGlassPointerEvents, shouldUseLiquidGlass } from './liquid-glass';

const backgroundSource = readFileSync(
  fileURLToPath(new URL('./liquid-glass-background.tsx', import.meta.url)),
  'utf8',
);
const modeSource = readFileSync(
  fileURLToPath(new URL('./liquid-glass-mode.tsx', import.meta.url)),
  'utf8',
);
const primaryButtonSource = readFileSync(
  fileURLToPath(new URL('./primary-button.tsx', import.meta.url)),
  'utf8',
);
const optionalSource = (path: string) => {
  const filePath = fileURLToPath(new URL(path, import.meta.url));
  return existsSync(filePath) ? readFileSync(filePath, 'utf8') : '';
};
const pressScaleSource = optionalSource('./press-scale-view.tsx');
const pressScaleContractSource = optionalSource('./press-scale.ts');
const source = (path: string) =>
  readFileSync(fileURLToPath(new URL(path, import.meta.url)), 'utf8');

describe('Liquid Glass availability', () => {
  it('keeps background-only surfaces out of hit testing and child hosts interactive', () => {
    expect(getLiquidGlassPointerEvents(false)).toBe('none');
    expect(getLiquidGlassPointerEvents(true)).toBe('auto');
    expect(backgroundSource).toContain('children?: ReactNode;');
    expect(backgroundSource).toContain('contentStyle?: StyleProp<ViewStyle>;');
    expect(backgroundSource).toContain('getLiquidGlassPointerEvents(hasChildren)');
    expect(backgroundSource).toContain('{children}');
    expect(backgroundSource).toContain("glassEffectStyle={useGlass ? glassEffectStyle : 'none'}");
    expect(backgroundSource).toContain("backgroundColor: useGlass ? 'transparent' : fallbackColor");
    expect(backgroundSource.match(/<GlassView/g)).toHaveLength(1);
    expect(backgroundSource).not.toContain('</View>');
  });

  it('keeps interactive descendants inside the native glass hosts', () => {
    const headerSource = source('../../features/onboarding/onboarding-header.tsx');
    const conversationSource = source('../../features/conversation/conversation-layout.tsx');
    const backStart = headerSource.indexOf('<LiquidGlassBackground');
    const backEnd = headerSource.indexOf('</LiquidGlassBackground>', backStart);
    const composerStart = conversationSource.indexOf('<LiquidGlassBackground');
    const composerEnd = conversationSource.indexOf('</LiquidGlassBackground>', composerStart);

    expect(headerSource.slice(backStart, backEnd)).toContain('<Image');
    expect(conversationSource.slice(composerStart, composerEnd)).toContain('<TextInput');
    expect(conversationSource.slice(composerStart, composerEnd)).toContain('<Pressable');
    expect(conversationSource).toContain('contentStyle={styles.composerContent}');
    expect(conversationSource).not.toContain("composer: { alignItems: 'center', flexDirection: 'row', overflow: 'hidden'");
  });

  it('uses glass only on a supported iOS device without Reduce Transparency', () => {
    expect(
      shouldUseLiquidGlass({
        apiAvailable: true,
        liquidGlassAvailable: true,
        platform: 'ios',
        reduceTransparency: false,
      }),
    ).toBe(true);

    expect(
      shouldUseLiquidGlass({
        apiAvailable: true,
        liquidGlassAvailable: true,
        platform: 'ios',
        reduceTransparency: false,
        forceFallback: true,
      }),
    ).toBe(false);

    for (const unavailable of [
      { apiAvailable: true, liquidGlassAvailable: true, platform: 'android', reduceTransparency: false },
      { apiAvailable: false, liquidGlassAvailable: true, platform: 'ios', reduceTransparency: false },
      { apiAvailable: true, liquidGlassAvailable: false, platform: 'ios', reduceTransparency: false },
      { apiAvailable: true, liquidGlassAvailable: true, platform: 'ios', reduceTransparency: true },
    ] as const) {
      expect(shouldUseLiquidGlass(unavailable)).toBe(false);
    }
  });

  it('provides a nonpersisted Zustand mode store and development-only iOS switch', () => {
    const layoutSource = source('../../app/_layout.tsx');

    expect(modeSource).toContain("import { create } from 'zustand';");
    expect(modeSource).toContain("mode: 'automatic'");
    expect(modeSource).toContain('useLiquidGlassModeStore.getState().setMode');
    expect(modeSource).not.toContain('createContext');
    expect(modeSource).not.toContain('activeModeSetter');
    expect(modeSource).not.toContain('persist');
    expect(modeSource).toContain("DevSettings.addMenuItem('Allies UI: Automatic Glass'");
    expect(modeSource).toContain("DevSettings.addMenuItem('Allies UI: Regular'");
    expect(modeSource).toContain("if (!__DEV__ || Platform.OS !== 'ios'");
    expect(layoutSource).toContain('LiquidGlassModeProvider');
    expect(backgroundSource).toContain("mode === 'regular'");
  });

  it('uses the shared press scale and glass fallback contracts', () => {
    const headerSource = source('../../features/onboarding/onboarding-header.tsx');
    const previewSource = source('../../features/onboarding/onboarding-preview-screen.tsx');
    const accountSource = source('../../app/account.tsx');
    const onboardingLayoutSource = source('../../features/onboarding/onboarding-layout.ts');

    expect(pressScaleContractSource).toContain('PRESS_SCALE = 1.075');
    expect(pressScaleContractSource).toContain('PRESS_SCALE_DURATION_MS = 140');
    expect(pressScaleSource).toContain('useReducedMotion');
    expect(pressScaleSource).toContain('pressedScale?: number');
    expect(pressScaleSource).toContain('pressedScale = PRESS_SCALE');
    expect(pressScaleSource).toContain('withTiming');
    expect(pressScaleSource).toContain('transform: [{ scale: scale.value }]');
    expect(pressScaleSource).toContain('pointerEvents="box-none"');
    expect(pressScaleSource).toMatch(/return \(\s*<Pressable[\s\S]*?<Animated\.View/);
    expect(primaryButtonSource).toContain('<PressScale');
    expect(headerSource).toContain('<PressScale');
    expect(previewSource).toContain('<PressScale');
    expect(primaryButtonSource).not.toContain('buttonPressed');
    expect(headerSource).not.toContain('backButtonPressed');
    expect(previewSource).not.toContain('accountPromptClosePressed');

    expect(primaryButtonSource).toContain('<LiquidGlassBackground');
    expect(primaryButtonSource).toContain('fallbackColor="transparent"');
    expect(primaryButtonSource).toContain('glassEffectStyle="regular"');
    expect(primaryButtonSource).toContain('isInteractive');
    expect(primaryButtonSource).toContain('isInteractive={!disabled}');
    expect(primaryButtonSource).toContain('pressedScale={1.03}');
    expect(primaryButtonSource).toContain('tintColor={disabled ? theme.inactiveButton : accentColor}');
    expect(primaryButtonSource).toContain('pointerEvents="none"');
    expect(primaryButtonSource).toContain('opacity: 0.72');

    expect(backgroundSource).toContain('isInteractive = true');
    expect(backgroundSource).toContain('useReducedMotion');
    expect(backgroundSource).toContain('const nativeIsInteractive = isInteractive && !reducedMotion');
    expect(backgroundSource).toContain('isInteractive={useGlass && nativeIsInteractive}');
    expect(backgroundSource).toContain('pointerEvents={pointerEvents}');
    expect(onboardingLayoutSource).toContain('ONBOARDING_HEADER_BUTTON_SIZE = 44');
    expect(headerSource).not.toContain('isInteractive=');
    expect(headerSource).toContain('height: 18');
    expect(headerSource).toContain('width: 10.3');
    expect(headerSource).toContain('hitSlop={8}');
    const backVisualStyleStart = headerSource.indexOf('backButtonPressable: {');
    const backVisualStyleEnd = headerSource.indexOf('\n  },', backVisualStyleStart);
    expect(headerSource.slice(backVisualStyleStart, backVisualStyleEnd)).not.toContain("overflow: 'hidden'");
    expect(accountSource).toContain('<OnboardingBackButton');
    expect(accountSource).not.toContain('backButton:');
    expect(accountSource).not.toContain('backIcon:');
    expect(accountSource).not.toContain('back-chevron-icon.svg');
  });

  it('reacts to Reduce Transparency and guards the native API', () => {
    expect(backgroundSource).toContain('isGlassEffectAPIAvailable()');
    expect(backgroundSource).toContain('isLiquidGlassAvailable()');
    expect(backgroundSource).toContain('isReduceTransparencyEnabled()');
    expect(backgroundSource).toContain("'reduceTransparencyChanged'");
    expect(backgroundSource).toContain('.remove()');
  });

  it('inverts only the native glass color scheme and keeps the fallback unchanged', () => {
    expect(backgroundSource).toContain('invertColorScheme?: boolean');
    expect(backgroundSource).toContain('const glassColorScheme = invertColorScheme');
    expect(backgroundSource).toContain('colorScheme={glassColorScheme}');
    expect(backgroundSource).toContain("backgroundColor: useGlass ? 'transparent' : fallbackColor");

    const previewSource = source('../../features/onboarding/onboarding-preview-screen.tsx');
    const closeStart = previewSource.indexOf('styles.accountPromptClose');
    const closeEnd = previewSource.indexOf('</Pressable>', closeStart);
    expect(previewSource.slice(closeStart, closeEnd)).toContain('invertColorScheme');
    expect((previewSource.match(/invertColorScheme/g) ?? [])).toHaveLength(1);
  });

  it('applies muted Ally tint only to onboarding editor and composer glass', () => {
    const jobSource = source('../../features/onboarding/onboarding-job-screen.tsx');
    const flowSource = source('../../features/onboarding/onboarding-flow.tsx');
    const personalitySource = source('../../features/onboarding/onboarding-personality-screen.tsx');
    const conversationSource = source('../../features/conversation/conversation-layout.tsx');

    const jobGlassTag = (jobSource.match(/<LiquidGlassBackground[\s\S]*?\/>/g) ?? [])
      .find((tag) => tag.includes('fallbackColor={isFocused ? theme.onboardingInputFocused : theme.onboardingInput}')) ?? '';
    expect(jobSource).toContain('accentColor: string;');
    expect(jobGlassTag).toContain('tintColor={getMutedOnboardingColor(accentColor, 0.02)}');
    expect(jobGlassTag).toContain('fallbackColor={isFocused ? theme.onboardingInputFocused : theme.onboardingInput}');

    const jobScreenStart = flowSource.indexOf('<OnboardingJobScreen');
    const jobScreenEnd = flowSource.indexOf('/>', jobScreenStart);
    expect(flowSource.slice(jobScreenStart, jobScreenEnd)).toContain('accentColor={accentColor}');

    const personalityGlassTags = personalitySource.match(/<LiquidGlassBackground[\s\S]*?\/>/g) ?? [];
    const personalityEditorTag = personalityGlassTags.find((tag) => tag.includes('fallbackColor={theme.onboardingInput}')) ?? '';
    const personalityHelpCloseTag = personalityGlassTags.find((tag) => tag.includes('fallbackColor={mutedColor}')) ?? '';
    expect(personalitySource).toContain('const mutedColor = getMutedOnboardingColor(accentColor);');
    expect(personalitySource).toContain('mutedColor={mutedColor}');
    expect(personalityEditorTag).toContain('tintColor={getMutedOnboardingColor(accentColor, 0.02)}');
    expect(personalityHelpCloseTag).not.toContain('tintColor=');

    expect(conversationSource).toContain(
      "const composerTintColor = headerMode === 'onboarding' ? getMutedOnboardingColor(ally.color, 0.02) : undefined;",
    );
    const composerGlassTag = conversationSource.match(/<LiquidGlassBackground[\s\S]*?\/>/)?.[0] ?? '';
    expect(composerGlassTag).toContain('tintColor={composerTintColor}');
    expect(composerGlassTag).toContain('fallbackColor={theme.chatInput}');

    const untintedGlassPaths = [
      '../../features/onboarding/onboarding-preview-screen.tsx',
      '../../app/account.tsx',
      '../../app/sign-in.tsx',
      '../../features/onboarding/onboarding-header.tsx',
    ];
    for (const path of untintedGlassPaths) {
      const currentSource = source(path);
      expect(currentSource).toContain('LiquidGlassBackground');
      for (const tag of currentSource.match(/<LiquidGlassBackground[\s\S]*?\/>/g) ?? []) {
        expect(tag).not.toContain('tintColor=');
      }
    }

    expect(source('../../features/onboarding/ally-name-screen.tsx')).not.toContain('LiquidGlassBackground');
    expect(source('../../app/auth/return.tsx')).not.toContain('liquidGlass');
  });
});
