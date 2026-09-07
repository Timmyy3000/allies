import { type ReactNode } from 'react';
import { Platform, StyleSheet, View } from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';

import { OnboardingHeader } from './onboarding-header';
import {
  ONBOARDING_IOS_TOP_PADDING,
  ONBOARDING_PAGE_HORIZONTAL_PADDING,
  ONBOARDING_TOP_PADDING,
} from './onboarding-layout';
import type { OnboardingChromeConfig } from './onboarding-shell-config';
import { useTheme } from '@/hooks/use-theme';

export {
  getOnboardingChrome,
  getOnboardingHeaderAllyVariant,
  isOnboardingFooterDisabled,
} from './onboarding-shell-config';
export type { OnboardingChromeConfig } from './onboarding-shell-config';

type OnboardingShellProps = OnboardingChromeConfig & {
  accentColor: string;
  children: ReactNode;
  centerContent?: boolean;
  footer?: ReactNode;
  onBack: () => void;
  titleAccessory?: ReactNode;
};

export function OnboardingShell({
  accentColor,
  centerContent = false,
  children,
  footer,
  onBack,
  progress,
  title,
  titleAccessory,
}: OnboardingShellProps) {
  const theme = useTheme();
  const { bottom: bottomInset } = useSafeAreaInsets();
  const isIosCenteredContent = centerContent && Platform.OS === 'ios';
  const contentAndFooter = (
    <>
      <View pointerEvents={isIosCenteredContent ? 'box-none' : 'auto'} style={styles.content}>
        {!isIosCenteredContent ? children : null}
      </View>

      {footer ? (
        <View style={[styles.footer, { paddingBottom: Math.max(0, 50 - bottomInset) }]}>
          {footer}
        </View>
      ) : null}
    </>
  );

  return (
    <View
      style={[styles.root, { backgroundColor: theme.appBackground }]}
    >

      <SafeAreaView
        edges={['top', 'bottom']}
        style={styles.safeArea}
      >
        <OnboardingHeader
          accentColor={accentColor}
          onBack={onBack}
          progress={progress}
          title={title}
          titleAccessory={titleAccessory}
        />

        {contentAndFooter}
      </SafeAreaView>

      {isIosCenteredContent ? (
        <View pointerEvents="box-none" style={styles.centeredContent}>
          {children}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  content: {
    flex: 1,
  },
  centeredContent: {
    bottom: 0,
    left: 0,
    position: 'absolute',
    right: 0,
    top: 0,
    zIndex: 1,
  },
  footer: {
    paddingHorizontal: 0,
  },
  root: {
    flex: 1,
    position: 'relative',
  },
  safeArea: {
    flex: 1,
    paddingHorizontal: ONBOARDING_PAGE_HORIZONTAL_PADDING,
    paddingTop: Platform.OS === 'ios' ? ONBOARDING_IOS_TOP_PADDING : ONBOARDING_TOP_PADDING,
  },
});
