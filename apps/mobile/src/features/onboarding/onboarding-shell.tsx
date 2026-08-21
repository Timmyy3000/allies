import { StatusBar } from 'expo-status-bar';
import { type ReactNode } from 'react';
import { StyleSheet, View } from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';

import { OnboardingHeader } from './onboarding-header';
import {
  ONBOARDING_PAGE_HORIZONTAL_PADDING,
  ONBOARDING_TOP_PADDING,
} from './onboarding-layout';
import type { OnboardingChromeConfig } from './onboarding-shell-config';

export {
  getOnboardingChrome,
  getOnboardingHeaderAllyVariant,
  isOnboardingFooterDisabled,
} from './onboarding-shell-config';
export type { OnboardingChromeConfig } from './onboarding-shell-config';

type OnboardingShellProps = OnboardingChromeConfig & {
  accentColor: string;
  children: ReactNode;
  footer?: ReactNode;
  onBack: () => void;
  titleAccessory?: ReactNode;
};

export function OnboardingShell({
  accentColor,
  children,
  footer,
  onBack,
  progress,
  title,
  titleAccessory,
}: OnboardingShellProps) {
  const { bottom: bottomInset } = useSafeAreaInsets();

  return (
    <View style={styles.root}>
      <StatusBar style="dark" />

      <SafeAreaView edges={['top', 'bottom']} style={styles.safeArea}>
        <OnboardingHeader
          accentColor={accentColor}
          onBack={onBack}
          progress={progress}
          title={title}
          titleAccessory={titleAccessory}
        />

        <View style={styles.content}>{children}</View>

        {footer ? (
          <View style={[styles.footer, { paddingBottom: Math.max(0, 50 - bottomInset) }]}>
            {footer}
          </View>
        ) : null}
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  content: {
    flex: 1,
  },
  footer: {
    paddingHorizontal: 0,
  },
  root: {
    backgroundColor: '#FFFFFF',
    flex: 1,
  },
  safeArea: {
    flex: 1,
    paddingHorizontal: ONBOARDING_PAGE_HORIZONTAL_PADDING,
    paddingTop: ONBOARDING_TOP_PADDING,
  },
});
