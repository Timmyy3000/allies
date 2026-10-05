import { useCallback, useEffect, useRef, useState } from 'react';
import { Keyboard, Platform, View, type KeyboardEvent } from 'react-native';
import {
  Easing,
  useAnimatedStyle,
  useDerivedValue,
  useReducedMotion,
  useSharedValue,
  withTiming,
} from 'react-native-reanimated';

import {
  ONBOARDING_EDITOR_HEIGHT,
  ONBOARDING_EDITOR_KEYBOARD_HEIGHT,
  ONBOARDING_EDITOR_RESIZE_DURATION_MS,
  ONBOARDING_EDITOR_RESIZE_EASING,
  getOnboardingEditorHeight,
  getOnboardingKeyboardPadding,
} from './onboarding-motion';

export function useOnboardingEditorHeight() {
  const reducedMotion = Boolean(useReducedMotion());
  const initiallyVisible = Keyboard.isVisible();
  const editorRef = useRef<View>(null);
  const expandedEditorBottom = useRef(0);
  const keyboardVisibleRef = useRef(initiallyVisible);
  const [keyboardVisible, setKeyboardVisible] = useState(initiallyVisible);
  const editorHeight = useSharedValue(getOnboardingEditorHeight(initiallyVisible));
  const editorLift = useSharedValue(0);
  const keyboardProgress = useDerivedValue(() =>
    (ONBOARDING_EDITOR_HEIGHT - editorHeight.value) /
    (ONBOARDING_EDITOR_HEIGHT - ONBOARDING_EDITOR_KEYBOARD_HEIGHT));

  const animateEditor = useCallback((visible: boolean, lift: number) => {
    const height = getOnboardingEditorHeight(visible);
    keyboardVisibleRef.current = visible;
    setKeyboardVisible(visible);

    if (reducedMotion) {
      editorHeight.set(height);
      editorLift.set(lift);
      return;
    }

    const animation = {
      duration: ONBOARDING_EDITOR_RESIZE_DURATION_MS,
      easing: Easing.bezier(...ONBOARDING_EDITOR_RESIZE_EASING),
    };
    editorHeight.set(withTiming(height, animation));
    editorLift.set(withTiming(lift, animation));
  }, [editorHeight, editorLift, reducedMotion]);

  const onEditorLayout = useCallback(() => {
    editorRef.current?.measureInWindow((_x, y) => {
      expandedEditorBottom.current = y + ONBOARDING_EDITOR_HEIGHT;
      const keyboard = Keyboard.metrics();

      if (keyboardVisibleRef.current && keyboard && Platform.OS === 'ios') {
        animateEditor(
          true,
          getOnboardingKeyboardPadding(expandedEditorBottom.current, keyboard.screenY),
        );
      }
    });
  }, [animateEditor]);

  useEffect(() => {
    const showEvent = Platform.OS === 'ios' ? 'keyboardWillShow' : 'keyboardDidShow';
    const hideEvent = Platform.OS === 'ios' ? 'keyboardWillHide' : 'keyboardDidHide';
    const handleKeyboardShow = (event: KeyboardEvent) => {
      const lift = Platform.OS === 'ios'
        ? getOnboardingKeyboardPadding(
            expandedEditorBottom.current,
            event.endCoordinates.screenY,
          )
        : 0;
      animateEditor(true, lift);
    };
    const handleKeyboardHide = () => animateEditor(false, 0);
    const handleKeyboardFrameChange = (event: KeyboardEvent) => {
      if (event.endCoordinates.height > 0) handleKeyboardShow(event);
    };
    const showSubscription = Keyboard.addListener(showEvent, handleKeyboardShow);
    const hideSubscription = Keyboard.addListener(hideEvent, handleKeyboardHide);
    const frameSubscription = Platform.OS === 'ios'
      ? Keyboard.addListener('keyboardWillChangeFrame', handleKeyboardFrameChange)
      : null;

    return () => {
      showSubscription.remove();
      hideSubscription.remove();
      frameSubscription?.remove();
    };
  }, [animateEditor]);

  const editorStyle = useAnimatedStyle(() => ({
    height: editorHeight.value,
    transform: [{
      translateY: -editorLift.value,
    }],
  }));

  return {
    editorRef,
    editorStyle,
    keyboardProgress,
    keyboardVisible,
    onEditorLayout,
  };
}
