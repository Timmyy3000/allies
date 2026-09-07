import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const screenSource = readFileSync(
  fileURLToPath(new URL('./onboarding-screen.tsx', import.meta.url)),
  'utf8',
);
const flowSource = readFileSync(
  fileURLToPath(new URL('./onboarding-flow.tsx', import.meta.url)),
  'utf8',
);
const signInPath = fileURLToPath(new URL('../../app/sign-in.tsx', import.meta.url));
const signInSource = existsSync(signInPath) ? readFileSync(signInPath, 'utf8') : '';
const nameRoutePath = fileURLToPath(new URL('../../app/onboarding/name.tsx', import.meta.url));
const nameRouteSource = existsSync(nameRoutePath) ? readFileSync(nameRoutePath, 'utf8') : '';

describe('welcome sign-in entry point', () => {
  it('keeps the sign-in prompt connected to the welcome layout contract', () => {
    expect(screenSource).toContain('Not new to this?');
    expect(screenSource).toContain('onPress={onSignIn}');
    expect(screenSource).toContain('marginTop: 24');
    expect(screenSource).toContain('SIGN_IN_BOTTOM_OFFSET = 60');
    expect(screenSource).toContain("fontFamily: 'OpenRundeSemibold'");
    expect(screenSource).toContain('fontSize: 16');
    expect(screenSource).toContain('letterSpacing: -0.7');
    expect(screenSource).toContain('lineHeight: 16');
    expect(screenSource).toContain("Not new to this?{' '}");
    expect(screenSource).toContain('accessibilityRole="link"');
    expect(screenSource).not.toContain('signInButton: {');
  });

  it('routes the prompt to the Google sign-in screen', () => {
    expect(flowSource).toContain("onSignIn={() => router.push('/sign-in')}");
    expect(signInSource).toContain('export default function SignInScreen');
    expect(signInSource).toContain('Continue with Google');
    expect(signInSource).not.toContain('Coming soon');
  });

  it('uses native navigation for welcome-to-name and returns each surface directly', () => {
    expect(flowSource).toContain("onStart={() => router.navigate('/onboarding/name' as never)}");
    expect(flowSource).toContain('<OnboardingScreen');
    expect(flowSource).toContain('<OnboardingPreviewScreen');
    expect(flowSource).toContain('return onboardingContent;');
    expect(flowSource).not.toContain('react-native-reanimated');
    expect(flowSource).not.toContain('FadeOutUp');
    expect(flowSource).not.toContain('FadeInDown');
    expect(flowSource).not.toContain('ONBOARDING_STEP_EXIT');
    expect(flowSource).not.toContain('ONBOARDING_STEP_ENTER');
  });

  it('configures a public native name route with reduced-motion and cold-entry back handling', () => {
    expect(nameRouteSource).toContain("import { Stack, useRouter } from 'expo-router'");
    expect(nameRouteSource).toContain('useReducedMotion');
    expect(nameRouteSource).toContain("animation: reducedMotion ? 'none' : 'default'");
    expect(nameRouteSource).toContain('gestureEnabled: false');
    expect(nameRouteSource).toContain('initialStep="name"');
    expect(nameRouteSource).toContain('router.canGoBack()');
    expect(nameRouteSource).toContain('router.back()');
    expect(nameRouteSource).toContain("router.replace('/')");
    expect(nameRouteSource).not.toContain('/allies/new');
  });

  it('keeps keyboard dismissal and later in-flow preview behavior in the flow', () => {
    expect(flowSource).toContain("BackHandler.addEventListener('hardwareBackPress'");
    expect(flowSource).toContain('handleBack();');
    expect(flowSource).toContain("Keyboard.addListener('keyboardDidHide'");
    expect(flowSource).toContain('await waitForKeyboardToHide();');
    expect(flowSource).toContain("step === 'preview'");
  });

  it('pauses the welcome Ally animation while its native route is unfocused', () => {
    expect(screenSource).toContain('useFocusEffect(useCallback(() => {');
    expect(screenSource).toContain('return () => cancelAnimation(idleProgress);');
  });
});
