import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import {
  ONBOARDING_EDITOR_HEIGHT,
  ONBOARDING_EDITOR_REGION_HEIGHT,
  ONBOARDING_EDITOR_KEYBOARD_HEIGHT,
  getOnboardingEditorHeight,
  getOnboardingKeyboardPadding,
} from './onboarding-motion';

const editorSources = [
  readFileSync(fileURLToPath(new URL('./onboarding-job-screen.tsx', import.meta.url)), 'utf8'),
  readFileSync(fileURLToPath(new URL('./onboarding-personality-screen.tsx', import.meta.url)), 'utf8'),
];
const hookPath = fileURLToPath(new URL('./use-onboarding-editor-height.ts', import.meta.url));
const hookSource = existsSync(hookPath) ? readFileSync(hookPath, 'utf8') : '';

describe('onboarding editor height', () => {
  it('keeps the normal and keyboard editor heights as a pure motion contract', () => {
    expect(ONBOARDING_EDITOR_HEIGHT).toBe(250);
    expect(ONBOARDING_EDITOR_REGION_HEIGHT).toBe(286);
    expect(ONBOARDING_EDITOR_KEYBOARD_HEIGHT).toBe(125);
    expect(getOnboardingEditorHeight(false)).toBe(250);
    expect(getOnboardingEditorHeight(true)).toBe(125);
    expect(getOnboardingKeyboardPadding(700, 600)).toBe(0);
    expect(getOnboardingKeyboardPadding(713, 600)).toBe(0);
    expect(getOnboardingKeyboardPadding(760, 600)).toBe(47);
  });

  it('uses one measured, interruptible UI-thread animation for each keyboard transition', () => {
    expect(hookSource).toContain('export function useOnboardingEditorHeight()');
    expect(hookSource).not.toContain('additionalKeyboardLift');
    expect(hookSource).toContain('const editorLift = useSharedValue(0);');
    expect(hookSource).toContain('translateY: -editorLift.value');
    expect(hookSource).not.toContain('    editorLift,\n    editorRef,');
    expect(hookSource).toContain('Keyboard.isVisible()');
    expect(hookSource).toContain('Keyboard.metrics()');
    expect(hookSource).toContain('keyboardWillShow');
    expect(hookSource).toContain('keyboardWillHide');
    expect(hookSource).toContain('keyboardWillChangeFrame');
    expect(hookSource).toContain('keyboardDidShow');
    expect(hookSource).toContain('keyboardDidHide');
    expect(hookSource).toContain('measureInWindow');
    expect(hookSource).toContain("keyboard && Platform.OS === 'ios'");
    expect(hookSource).toContain('withTiming');
    expect(hookSource).toContain('useReducedMotion()');
    expect(hookSource).not.toContain('LayoutAnimation');
    expect(hookSource).not.toContain('useFrameCallback');
    expect(hookSource).toContain('.remove()');
  });

  it('moves only the fixed editor region and hides its counter while the keyboard is visible', () => {
    for (const source of editorSources) {
      expect(source).toContain('useOnboardingEditorHeight();');
      expect(source).toContain("Platform.OS === 'ios'");
      expect(source).toContain('<KeyboardAvoidingView behavior="height"');
      expect(source).not.toContain('keyboardPaddingBottom');
      expect(source).not.toContain('onKeyboardViewLayout');
      expect(source).toContain('keyboardVisible');
      expect(source).toContain('ref={editorRef}');
      expect(source).toContain('onLayout={onEditorLayout}');
      expect(source).toContain('editorRegion');
      expect(source).toContain('editorStyle');
      expect(source).toContain('{!keyboardVisible ? (');
      expect(source).toContain('flex: 1');
      expect(source).toContain('scrollEnabled');
      expect(source).toContain('ONBOARDING_EDITOR_HEIGHT');
      expect(source).toContain('height: ONBOARDING_EDITOR_HEIGHT');
    }
    expect(editorSources[1]).not.toContain('editorLift');
  });
});
