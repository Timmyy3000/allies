import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import {
  cancelAnimation,
  Easing,
  useReducedMotion,
  useSharedValue,
  withRepeat,
  withTiming,
} from 'react-native-reanimated';

import { PrimaryButton } from '@/components/ui/primary-button';

import { AlliesLogo } from './allies-logo';
import { AllyCharacter } from './ally-character';
import { ALLY_IDLE_PERIOD_MS } from './ally-idle-sprite-motion';
import { FLOATING_ALLIES } from './onboarding-characters';
import { WELCOME_CTA_LABEL } from './onboarding-motion';
import { DEFAULT_ONBOARDING_ACCENT } from './onboarding-state';

type OnboardingScreenProps = {
  accentColor?: string;
  onStart?: () => void;
  onSignIn?: () => void;
};

const LOGO_WIDTH = 100;
const LOGO_HEIGHT = LOGO_WIDTH * (86 / 89);
const SIGN_IN_BOTTOM_OFFSET = 60;

export default function OnboardingScreen({
  accentColor = DEFAULT_ONBOARDING_ACCENT,
  onStart,
  onSignIn,
}: OnboardingScreenProps) {
  const { bottom: bottomInset } = useSafeAreaInsets();
  const reducedMotion = useReducedMotion();
  const idleProgress = useSharedValue(0);

  useEffect(() => {
    if (reducedMotion) {
      idleProgress.value = 0;
      return;
    }

    idleProgress.value = withRepeat(
      withTiming(1, { duration: ALLY_IDLE_PERIOD_MS, easing: Easing.linear }),
      -1,
      false,
    );

    return () => cancelAnimation(idleProgress);
  }, [idleProgress, reducedMotion]);

  return (
    <View style={styles.root}>
      <StatusBar style="dark" />

      <SafeAreaView edges={['top', 'bottom']} style={styles.safeArea}>
        <View style={styles.visualArea}>
          {FLOATING_ALLIES.map((ally) => (
            <AllyCharacter
              ally={ally}
              idleProgress={idleProgress}
              key={ally.color}
            />
          ))}
        </View>

        <View
          style={[
            styles.footer,
            { paddingBottom: Math.max(0, SIGN_IN_BOTTOM_OFFSET - bottomInset) },
          ]}>
          <PrimaryButton
            accentColor={accentColor}
            label={WELCOME_CTA_LABEL}
            onPress={onStart}
          />

          <View style={styles.signInRow}>
            <Text style={styles.signInPrompt}>Not new to this?</Text>
            <Pressable accessibilityRole="link" onPress={onSignIn} style={styles.signInButton}>
              <Text style={[styles.signIn, { color: accentColor }]}>Sign in</Text>
            </Pressable>
          </View>
        </View>
      </SafeAreaView>

      <View pointerEvents="none" style={styles.logoOverlay}>
        <AlliesLogo height={LOGO_HEIGHT} width={LOGO_WIDTH} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  footer: {
    paddingHorizontal: 14,
  },
  logoOverlay: {
    alignItems: 'center',
    bottom: 0,
    justifyContent: 'center',
    left: 0,
    position: 'absolute',
    right: 0,
    top: 0,
    zIndex: 1,
  },
  root: {
    backgroundColor: '#FFFFFF',
    flex: 1,
    position: 'relative',
  },
  safeArea: {
    flex: 1,
  },
  signIn: {
    fontFamily: 'OpenRundeSemibold',
  },
  signInButton: {
    minHeight: 20,
    paddingLeft: 4,
  },
  signInPrompt: {
    color: '#111111',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 16,
    letterSpacing: -0.7,
    lineHeight: 20,
    textAlign: 'center',
  },
  signInRow: {
    alignItems: 'center',
    flexDirection: 'row',
    justifyContent: 'center',
  },
  visualArea: {
    flex: 1,
    overflow: 'hidden',
    position: 'relative',
  },
});
