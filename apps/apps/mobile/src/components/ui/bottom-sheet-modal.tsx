import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import {
  Modal,
  Pressable,
  StyleSheet,
  useWindowDimensions,
  type StyleProp,
  type ViewStyle,
} from 'react-native';
import {
  Gesture,
  GestureDetector,
  GestureHandlerRootView,
} from 'react-native-gesture-handler';
import Animated, {
  cancelAnimation,
  Easing,
  runOnJS,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withSpring,
  withTiming,
} from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import {
  getBottomSheetAnimationTarget,
  shouldDismissBottomSheet,
} from './bottom-sheet-motion';
import { useTheme } from '@/hooks/use-theme';

type BottomSheetModalProps = {
  accessibilityLabel?: string;
  children: ReactNode;
  onClose: () => void;
  sheetStyle?: StyleProp<ViewStyle>;
  visible: boolean;
};

export function BottomSheetModal({
  accessibilityLabel = 'Close bottom sheet',
  children,
  onClose,
  sheetStyle,
  visible,
}: BottomSheetModalProps) {
  const theme = useTheme();
  const { bottom: bottomInset } = useSafeAreaInsets();
  const { height: viewportHeight } = useWindowDimensions();
  const reducedMotion = Boolean(useReducedMotion());
  const [mounted, setMounted] = useState(false);
  const mountedRef = useRef(false);
  const transitionRef = useRef(0);
  const overlayOpacity = useSharedValue(0);
  const sheetTranslateY = useSharedValue(viewportHeight);
  const gestureStartY = useSharedValue(0);
  const handleSheetDismissed = useCallback((transitionId: number) => {
    if (transitionId !== transitionRef.current) return;
    mountedRef.current = false;
    setMounted(false);
  }, []);
  const overlayStyle = useAnimatedStyle(() => ({
    opacity: overlayOpacity.value,
  }));
  const sheetAnimationStyle = useAnimatedStyle(() => ({
    transform: [{ translateY: sheetTranslateY.value }],
  }));
  const startEnter = useCallback((transitionId: number) => {
    if (transitionId !== transitionRef.current) return;

    const target = getBottomSheetAnimationTarget(true, reducedMotion, viewportHeight);
    cancelAnimation(overlayOpacity);
    cancelAnimation(sheetTranslateY);

    if (target.duration === 0) {
      overlayOpacity.set(target.overlayOpacity);
      sheetTranslateY.set(target.translateY);
      return;
    }

    overlayOpacity.set(withTiming(target.overlayOpacity, {
      duration: target.duration,
      easing: Easing.inOut(Easing.quad),
    }));
    sheetTranslateY.set(withTiming(target.translateY, {
      duration: target.duration,
      easing: Easing.out(Easing.cubic),
    }));
  }, [overlayOpacity, reducedMotion, sheetTranslateY, viewportHeight]);
  const handleModalShown = useCallback(() => {
    startEnter(transitionRef.current);
  }, [startEnter]);
  const handleGestureDismiss = useCallback(() => {
    onClose();
  }, [onClose]);
  const panGesture = Gesture.Pan()
    .activeOffsetY(8)
    .failOffsetX([-24, 24])
    .onBegin(() => {
      cancelAnimation(sheetTranslateY);
      gestureStartY.set(sheetTranslateY.value);
    })
    .onUpdate((event) => {
      sheetTranslateY.set(Math.max(0, gestureStartY.value + event.translationY));
    })
    .onEnd((event) => {
      if (shouldDismissBottomSheet(event.translationY, event.velocityY, viewportHeight)) {
        runOnJS(handleGestureDismiss)();
        return;
      }

      if (reducedMotion) {
        sheetTranslateY.set(0);
        return;
      }

      sheetTranslateY.set(withSpring(0, {
        damping: 30,
        stiffness: 360,
      }));
    });

  useEffect(() => {
    const transitionId = transitionRef.current + 1;
    transitionRef.current = transitionId;
    const target = getBottomSheetAnimationTarget(visible, reducedMotion, viewportHeight);
    cancelAnimation(overlayOpacity);
    cancelAnimation(sheetTranslateY);
    let frame: number | undefined;

    const cleanup = () => {
      if (frame !== undefined) cancelAnimationFrame(frame);
      cancelAnimation(overlayOpacity);
      cancelAnimation(sheetTranslateY);
    };

    if (visible) {
      if (mountedRef.current) {
        startEnter(transitionId);
        return cleanup;
      }

      frame = requestAnimationFrame(() => {
        mountedRef.current = true;
        overlayOpacity.set(0);
        sheetTranslateY.set(viewportHeight);
        setMounted(true);
      });
      return cleanup;
    }

    if (!mountedRef.current) return cleanup;
    if (target.duration === 0) {
      overlayOpacity.set(target.overlayOpacity);
      sheetTranslateY.set(target.translateY);
      frame = requestAnimationFrame(() => handleSheetDismissed(transitionId));
      return cleanup;
    }

    overlayOpacity.set(withTiming(target.overlayOpacity, {
      duration: target.duration,
      easing: Easing.inOut(Easing.quad),
    }));
    sheetTranslateY.set(withTiming(
      target.translateY,
      {
        duration: target.duration,
        easing: Easing.in(Easing.cubic),
      },
      (finished) => {
        'worklet';
        if (finished) runOnJS(handleSheetDismissed)(transitionId);
      },
    ));

    return cleanup;
  }, [
    handleSheetDismissed,
    overlayOpacity,
    reducedMotion,
    sheetTranslateY,
    startEnter,
    viewportHeight,
    visible,
  ]);

  if (!mounted) return null;

  return (
    <Modal
      animationType="none"
      onRequestClose={onClose}
      onShow={handleModalShown}
      presentationStyle="overFullScreen"
      statusBarTranslucent
      transparent
      visible={mounted}>
      <GestureHandlerRootView style={styles.container}>
        <Animated.View
          pointerEvents="none"
          style={[StyleSheet.absoluteFill, styles.backdrop, overlayStyle]}
        />
        <Pressable
          accessibilityLabel={accessibilityLabel}
          accessibilityRole="button"
          onPress={onClose}
          style={StyleSheet.absoluteFill}
        />
        <GestureDetector gesture={panGesture}>
          <Animated.View
            style={[
              styles.sheet,
              { backgroundColor: theme.modalSurface },
              { paddingBottom: Math.max(16, bottomInset + 12) },
              sheetStyle,
              sheetAnimationStyle,
            ]}>
            {children}
          </Animated.View>
        </GestureDetector>
      </GestureHandlerRootView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    backgroundColor: 'rgba(0, 0, 0, 0.28)',
  },
  container: {
    flex: 1,
    justifyContent: 'flex-end',
  },
  sheet: {
    alignSelf: 'stretch',
    borderRadius: 30,
    elevation: 0,
    marginBottom: 24,
    marginHorizontal: 12,
  },
});
