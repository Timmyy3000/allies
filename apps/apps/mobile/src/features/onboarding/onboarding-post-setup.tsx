import { useEffect, useId, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import Svg, { Defs, LinearGradient, Rect, Stop } from 'react-native-svg';
import Animated, {
  cancelAnimation,
  Easing,
  FadeIn,
  interpolate,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withDelay,
  withRepeat,
  withSequence,
  withTiming,
} from 'react-native-reanimated';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';

import { PrimaryButton } from '@/components/ui/primary-button';
import { useTheme } from '@/hooks/use-theme';

import { OnboardingAllyPreview } from './onboarding-ally-preview';
import {
  ONBOARDING_BASICS_BOUNCE_LIFT,
  ONBOARDING_POST_SETUP_DURATION_MS,
  ONBOARDING_POST_SETUP_FADE_DURATION_MS,
} from './onboarding-motion';
import type { AllyColorValue, AllyShape } from './onboarding-state';

type OnboardingBasicsScreenProps = {
  allyName: string;
  allyShape: AllyShape;
  selectedColor: AllyColorValue | null;
  onComplete: () => void;
};

type OnboardingNotificationsScreenProps = {
  allyShape: AllyShape;
  selectedColor: AllyColorValue | null;
  onAllow: () => void | Promise<void>;
  onSkip: () => void | Promise<void>;
};

const POST_SETUP_EASING = Easing.out(Easing.cubic);
const NOTIFICATION_SHEEN_DURATION_MS = 2000;
const NOTIFICATION_SHEEN_PAUSE_MS = 2500;
const NOTIFICATION_SHEEN_STAGGER_MS = 220;

type BouncingAllyProps = {
  allyName: string;
  allyShape: AllyShape;
  selectedColor: AllyColorValue | null;
};

function BouncingAlly({ allyName, allyShape, selectedColor }: BouncingAllyProps) {
  const reducedMotion = Boolean(useReducedMotion());
  const bounceProgress = useSharedValue(0);

  useEffect(() => {
    cancelAnimation(bounceProgress);

    if (reducedMotion) {
      bounceProgress.value = 0;
      return;
    }

    bounceProgress.value = withRepeat(
      withSequence(
        withTiming(0.18, { duration: 70, easing: Easing.out(Easing.cubic) }),
        withTiming(0.6, { duration: 160, easing: Easing.out(Easing.quad) }),
        withTiming(0.82, { duration: 270, easing: Easing.in(Easing.quad) }),
        withTiming(1, { duration: 99, easing: Easing.out(Easing.cubic) }),
        withDelay(120, withTiming(0, { duration: 1 })),
      ),
      -1,
      false,
    );

    return () => cancelAnimation(bounceProgress);
  }, [bounceProgress, reducedMotion]);

  const bounceStyle = useAnimatedStyle(() => ({
    transform: [
      {
        translateY: interpolate(
          bounceProgress.value,
          [0, 0.18, 0.6, 0.82, 1],
          [0, 0, -ONBOARDING_BASICS_BOUNCE_LIFT, 0, 0],
        ),
      },
      {
        scaleX: interpolate(bounceProgress.value, [0, 0.18, 0.6, 0.82, 1], [1, 1.08, 0.94, 1.1, 1]),
      },
      {
        scaleY: interpolate(bounceProgress.value, [0, 0.18, 0.6, 0.82, 1], [1, 0.9, 1.08, 0.9, 1]),
      },
    ],
  }));

  return (
    <Animated.View style={[styles.basicsAllyBounce, bounceStyle]}>
      <OnboardingAllyPreview
        accessibilityLabel={`${allyName || 'Your'} Ally`}
        artworkScale={0.86}
        color={selectedColor}
        identity={allyShape}
        size={56}
      />
    </Animated.View>
  );
}

type NotificationSkeletonBarProps = {
  backgroundColor: string;
  delay: number;
  height: number;
  width: number;
};

function NotificationSkeletonBar({
  backgroundColor,
  delay,
  height,
  width,
}: NotificationSkeletonBarProps) {
  const reducedMotion = Boolean(useReducedMotion());
  const sheenProgress = useSharedValue(0);
  const gradientId = useId().replace(/:/g, '');
  const sheenWidth = Math.max(20, width * 0.45);

  useEffect(() => {
    cancelAnimation(sheenProgress);

    if (reducedMotion) {
      sheenProgress.value = 0;
      return;
    }

    sheenProgress.value = withDelay(
      delay,
      withRepeat(
        withSequence(
          withTiming(1, {
            duration: NOTIFICATION_SHEEN_DURATION_MS,
            easing: Easing.linear,
          }),
          withDelay(NOTIFICATION_SHEEN_PAUSE_MS, withTiming(0, { duration: 0 })),
        ),
        -1,
        false,
      ),
    );

    return () => cancelAnimation(sheenProgress);
  }, [delay, reducedMotion, sheenProgress]);

  const sheenStyle = useAnimatedStyle(() => ({
    transform: [
      {
        translateX: interpolate(sheenProgress.value, [0, 1], [-sheenWidth, width]),
      },
    ],
  }));

  return (
    <View
      importantForAccessibility="no"
      pointerEvents="none"
      style={[styles.notificationSkeletonBar, { backgroundColor, height, width }]}
    >
      <Animated.View
        pointerEvents="none"
        style={[styles.notificationSheen, { height, width: sheenWidth }, sheenStyle]}>
        <Svg height={height} width={sheenWidth}>
          <Defs>
            <LinearGradient id={gradientId} x1="0%" x2="100%" y1="0%" y2="0%">
              <Stop offset="0%" stopColor="#FFFFFF" stopOpacity="0" />
              <Stop offset="50%" stopColor="#FFFFFF" stopOpacity="0.18" />
              <Stop offset="100%" stopColor="#FFFFFF" stopOpacity="0" />
            </LinearGradient>
          </Defs>
          <Rect fill={'url(#' + gradientId + ')'} height="100%" width="100%" />
        </Svg>
      </Animated.View>
    </View>
  );
}

export function OnboardingBasicsScreen({
  allyName,
  allyShape,
  onComplete,
  selectedColor,
}: OnboardingBasicsScreenProps) {
  const theme = useTheme();
  const reducedMotion = Boolean(useReducedMotion());

  useEffect(() => {
    const timer = setTimeout(onComplete, ONBOARDING_POST_SETUP_DURATION_MS);
    return () => clearTimeout(timer);
  }, [onComplete]);

  return (
    <View style={[styles.root, { backgroundColor: theme.appBackground }]}>
      <SafeAreaView edges={['top', 'bottom']} style={styles.safeArea}>
        <Animated.View
          entering={
            reducedMotion
              ? undefined
              : FadeIn.duration(ONBOARDING_POST_SETUP_FADE_DURATION_MS).easing(POST_SETUP_EASING)
          }
          style={styles.basicsContent}>
          <BouncingAlly
            allyName={allyName}
            allyShape={allyShape}
            selectedColor={selectedColor}
          />
          <Text style={[styles.basicsTitle, { color: theme.primaryText }]}>Looking good, {allyName || 'your Ally'}</Text>
          <Text style={[styles.basicsSubtitle, { color: theme.supportingText }]}>We’re done with the basics, one more thing</Text>
        </Animated.View>
      </SafeAreaView>
    </View>
  );
}

export function OnboardingNotificationsScreen({
  allyShape,
  onAllow,
  onSkip,
  selectedColor,
}: OnboardingNotificationsScreenProps) {
  const theme = useTheme();
  const { bottom: bottomInset } = useSafeAreaInsets();
  const reducedMotion = Boolean(useReducedMotion());
  const accentColor = selectedColor ?? '#FF5800';
  const [isActionPending, setIsActionPending] = useState(false);

  const runAction = async (action: () => void | Promise<void>) => {
    if (isActionPending) return;
    setIsActionPending(true);
    try {
      await action();
    } catch {
      // The flow owns continuation so a native permission failure cannot strand onboarding.
    } finally {
      setIsActionPending(false);
    }
  };

  return (
    <View style={[styles.root, { backgroundColor: theme.appBackground }]}>
      <SafeAreaView edges={['top', 'bottom']} style={styles.notificationSafeArea}>
        <Animated.View
          entering={
            reducedMotion
              ? undefined
              : FadeIn.duration(ONBOARDING_POST_SETUP_FADE_DURATION_MS).easing(POST_SETUP_EASING)
          }
          style={styles.notificationContent}>
          <View
            accessibilityLabel="Example ally notification"
            style={[styles.notificationPreview, { backgroundColor: theme.controlSurface }]}
          >
            <View style={[styles.notificationAllyTile, { backgroundColor: accentColor }]}>
              <OnboardingAllyPreview
                accessibilityLabel="Ally notification preview"
                color={accentColor}
                identity={allyShape}
                size={48}
              />
            </View>
            <View style={styles.notificationSkeleton}>
              <NotificationSkeletonBar
                backgroundColor={theme.inactiveButton}
                delay={0}
                height={18}
                width={60}
              />
              <NotificationSkeletonBar
                backgroundColor={theme.inactiveButton}
                delay={NOTIFICATION_SHEEN_STAGGER_MS}
                height={14}
                width={213}
              />
            </View>
          </View>

          <Text style={[styles.notificationTitle, { color: theme.primaryText }]}>Keep up with your allies</Text>
          <Text style={[styles.notificationSubtitle, { color: theme.supportingText }]}>
            Allow notifications so you can track tasks,{ '\n' }
            reminders, and reach goals faster
          </Text>
        </Animated.View>

        <View style={[styles.notificationFooter, { paddingBottom: Math.max(0, 50 - bottomInset) }]}>
          <PrimaryButton
            accentColor={theme.neutralButtonSurface}
            bottomMargin={0}
            disabled={isActionPending}
            label="I’ll do this later"
            labelColor={theme.neutralButtonText}
            onPress={() => void runAction(onSkip)}
          />
          <PrimaryButton
            accentColor={accentColor}
            bottomMargin={0}
            disabled={isActionPending}
            label="Allow notifications"
            onPress={() => void runAction(onAllow)}
          />
        </View>
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  basicsAllyBounce: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  basicsContent: {
    alignItems: 'center',
    flex: 1,
    justifyContent: 'center',
    paddingHorizontal: 14,
  },
  basicsSubtitle: {
    fontFamily: 'OpenRundeMedium',
    fontSize: 16,
    letterSpacing: -0.5,
    lineHeight: 16,
    marginTop: 12,
    textAlign: 'center',
  },
  basicsTitle: {
    fontFamily: 'OpenRundeSemibold',
    fontSize: 24,
    letterSpacing: -1,
    lineHeight: 24,
    marginTop: 18,
    textAlign: 'center',
  },
  notificationAllyTile: {
    alignItems: 'center',
    borderRadius: 14,
    height: 50,
    justifyContent: 'center',
    width: 50,
  },
  notificationContent: {
    alignItems: 'center',
    flex: 1,
    justifyContent: 'center',
    paddingBottom: 18,
    paddingHorizontal: 10,
  },
  notificationFooter: {
    gap: 18,
    paddingHorizontal: 14,
  },
  notificationPreview: {
    alignItems: 'center',
    borderRadius: 16,
    flexDirection: 'row',
    height: 74,
    maxWidth: 320,
    paddingHorizontal: 14,
    paddingVertical: 12,
    width: '100%',
  },
  notificationSafeArea: {
    flex: 1,
  },
  notificationSkeleton: {
    flex: 1,
    gap: 8,
    justifyContent: 'center',
    marginLeft: 12,
  },
  notificationSkeletonBar: {
    borderRadius: 4,
    overflow: 'hidden',
  },
  notificationSheen: {
    position: 'absolute',
    top: 0,
  },
  notificationSubtitle: {
    fontFamily: 'OpenRundeMedium',
    fontSize: 16,
    letterSpacing: -0.5,
    lineHeight: 16,
    marginTop: 12,
    textAlign: 'center',
  },
  notificationTitle: {
    fontFamily: 'OpenRundeSemibold',
    fontSize: 20,
    letterSpacing: -1,
    lineHeight: 20,
    marginTop: 36,
    textAlign: 'center',
  },
  root: {
    flex: 1,
  },
  safeArea: {
    flex: 1,
  },
});
