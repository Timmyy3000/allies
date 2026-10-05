import { Image } from 'expo-image';
import { type ReactNode } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { LiquidGlassBackground } from '@/components/ui/liquid-glass-background';
import { PressScale } from '@/components/ui/press-scale-view';
import { OnboardingProgress } from './onboarding-progress';
import { useTheme } from '@/hooks/use-theme';
import {
  ONBOARDING_HEADER_BUTTON_SIZE,
  ONBOARDING_HEADER_LINE_HEIGHT,
  ONBOARDING_HEADER_ROW_TO_ACCESSORY_GAP,
} from './onboarding-layout';

type OnboardingHeaderProps = {
  accentColor: string;
  onBack: () => void;
  progress: number;
  title: string;
  titleAccessory?: ReactNode;
};

export function OnboardingBackButton({
  accessibilityLabel = 'Go back',
  onBack,
}: {
  accessibilityLabel?: string;
  onBack: () => void;
}) {
  const theme = useTheme();

  return (
    <PressScale
      accessibilityLabel={accessibilityLabel}
      accessibilityRole="button"
      hitSlop={8}
      onPress={onBack}
      pressableStyle={styles.backButtonPressable}
      style={styles.backButton}>
        <LiquidGlassBackground
          borderRadius={ONBOARDING_HEADER_BUTTON_SIZE / 2}
          contentStyle={styles.backButtonContent}
          fallbackColor={theme.controlSurface}
        >
          <Image
            accessibilityLabel="Back"
            contentFit="contain"
            source={require('@/assets/allies/icons/back-chevron-icon.svg')}
            style={[styles.chevron, { tintColor: theme.icon }]}
          />
        </LiquidGlassBackground>
    </PressScale>
  );
}

export function OnboardingHeader({
  accentColor,
  onBack,
  progress,
  title,
  titleAccessory,
}: OnboardingHeaderProps) {
  const theme = useTheme();
  return (
    <View style={styles.container}>
      <OnboardingBackButton onBack={onBack} />

      <View style={styles.progress}>
        <OnboardingProgress accentColor={accentColor} progress={progress} />
      </View>

      {titleAccessory ? <View style={styles.titleAccessory}>{titleAccessory}</View> : null}
      <Text style={[styles.title, { color: theme.primaryText }, titleAccessory ? styles.titleWithAccessory : undefined]}>
        {title}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  backButton: {
    height: ONBOARDING_HEADER_BUTTON_SIZE,
    width: ONBOARDING_HEADER_BUTTON_SIZE,
  },
  backButtonPressable: {
    alignItems: 'center',
    borderRadius: ONBOARDING_HEADER_BUTTON_SIZE / 2,
    flex: 1,
    justifyContent: 'center',
  },
  backButtonContent: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  chevron: {
    height: 18,
    width: 10.3,
  },
  container: {
    position: 'relative',
  },
  progress: {
    position: 'absolute',
    right: 0,
    top: 0,
  },
  title: {
    fontFamily: 'OpenRundeSemibold',
    fontSize: 24,
    includeFontPadding: false,
    letterSpacing: -1,
    lineHeight: ONBOARDING_HEADER_LINE_HEIGHT,
    marginTop: 24,
    maxWidth: '78%',
  },
  titleAccessory: {
    marginTop: ONBOARDING_HEADER_ROW_TO_ACCESSORY_GAP,
  },
  titleWithAccessory: {
    marginTop: 16,
  },
});
