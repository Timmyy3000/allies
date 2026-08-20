import { Image } from 'expo-image';
import { type ReactNode } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { OnboardingProgress } from './onboarding-progress';
import { ONBOARDING_HEADER_LINE_HEIGHT } from './onboarding-layout';

type OnboardingHeaderProps = {
  accentColor: string;
  onBack: () => void;
  progress: number;
  title: string;
  titleAccessory?: ReactNode;
};

export function OnboardingHeader({
  accentColor,
  onBack,
  progress,
  title,
  titleAccessory,
}: OnboardingHeaderProps) {
  return (
    <View style={styles.container}>
      <Pressable
        accessibilityLabel="Go back"
        accessibilityRole="button"
        hitSlop={8}
        onPress={onBack}
        style={({ pressed }) => [styles.backButton, pressed && styles.backButtonPressed]}>
        <Image
          accessibilityLabel="Back"
          contentFit="contain"
          source={require('@/assets/allies/icons/back-chevron-icon.svg')}
          style={styles.chevron}
        />
      </Pressable>

      <View style={styles.progress}>
        <OnboardingProgress accentColor={accentColor} progress={progress} />
      </View>

      {titleAccessory ? <View style={styles.titleAccessory}>{titleAccessory}</View> : null}
      <Text style={[styles.title, titleAccessory ? styles.titleWithAccessory : undefined]}>
        {title}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  backButton: {
    alignItems: 'center',
    backgroundColor: '#F3F3F3',
    borderRadius: 20,
    height: 40,
    justifyContent: 'center',
    width: 40,
  },
  backButtonPressed: {
    opacity: 0.76,
  },
  chevron: {
    height: 14,
    width: 8,
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
    color: '#111111',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 24,
    includeFontPadding: false,
    letterSpacing: -1,
    lineHeight: ONBOARDING_HEADER_LINE_HEIGHT,
    marginTop: 24,
    maxWidth: '78%',
  },
  titleAccessory: {
    marginTop: 12,
  },
  titleWithAccessory: {
    marginTop: 16,
  },
});
