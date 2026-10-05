import { useLocalSearchParams, useRouter } from 'expo-router';
import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { useAlly } from '@/features/allies/queries';
import { getAllyAppearance } from '@/features/allies/ally-appearance';
import { OnboardingBasicsScreen, OnboardingNotificationsScreen } from '@/features/onboarding/onboarding-post-setup';
import { OnboardingAllyPreview } from '@/features/onboarding/onboarding-ally-preview';
import { requestNotificationPermission } from '@/lib/notifications/notification-permission';
import { useTheme } from '@/hooks/use-theme';

export default function PostSetupScreen() {
  const router = useRouter();
  const { allyId: allyIdParam } = useLocalSearchParams<{ allyId?: string }>();
  const allyId = Array.isArray(allyIdParam) ? allyIdParam[0] : allyIdParam ?? null;
  const allyQuery = useAlly(allyId);
  const [step, setStep] = useState<'basics' | 'notifications'>('basics');

  if (!allyId) {
    return (
      <StatusScreen
        actionLabel="Start another Ally"
        message="We could not find the Ally you just created."
        onAction={() => router.replace('/allies/new' as never)}
        secondaryLabel="Open Allies"
        onSecondary={() => router.replace('/allies' as never)}
      />
    );
  }
  if (allyQuery.isPending) {
    return <StatusScreen busy message="Getting your Ally ready…" />;
  }
  if (allyQuery.isError || !allyQuery.data) {
    return (
      <StatusScreen
        actionLabel="Try again"
        message="We could not load your new Ally yet."
        onAction={() => void allyQuery.refetch()}
        secondaryLabel="Open Allies"
        onSecondary={() => router.replace('/allies' as never)}
      />
    );
  }

  const ally = allyQuery.data;
  const appearance = getAllyAppearance(ally.appearance.key);
  const openConversation = () => router.replace(`/allies/${encodeURIComponent(ally.id)}` as never);

  if (step === 'basics') {
    return (
      <OnboardingBasicsScreen
        allyName={ally.name}
        allyShape={appearance.shape}
        onComplete={() => setStep('notifications')}
        selectedColor={appearance.color}
      />
    );
  }

  return (
    <OnboardingNotificationsScreen
      allyShape={appearance.shape}
      onAllow={async () => {
        try {
          await requestNotificationPermission();
        } finally {
          openConversation();
        }
      }}
      onSkip={openConversation}
      selectedColor={appearance.color}
    />
  );
}

function StatusScreen({
  actionLabel,
  busy = false,
  message,
  onAction,
  onSecondary,
  secondaryLabel,
}: {
  actionLabel?: string;
  busy?: boolean;
  message: string;
  onAction?: () => void;
  onSecondary?: () => void;
  secondaryLabel?: string;
}) {
  const theme = useTheme();
  return (
    <View style={[styles.status, { backgroundColor: theme.appBackground }]}>
      {busy ? <OnboardingAllyPreview accessibilityLabel="Ally getting ready" color="#FF7A00" identity="boxy" size={84} state="thinking" /> : null}
      <Text style={[styles.statusText, { color: theme.primaryText }]}>{message}</Text>
      {actionLabel && onAction ? (
        <Pressable accessibilityRole="button" onPress={onAction} style={[styles.action, { backgroundColor: theme.primaryText }]}>
          <Text style={[styles.actionText, { color: theme.appBackground }]}>{actionLabel}</Text>
        </Pressable>
      ) : null}
      {secondaryLabel && onSecondary ? (
        <Pressable accessibilityRole="button" onPress={onSecondary} style={styles.secondary}>
          <Text style={[styles.secondaryText, { color: theme.supportingText }]}>{secondaryLabel}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  action: { borderRadius: 999, marginTop: 24, paddingHorizontal: 24, paddingVertical: 13 },
  actionText: { fontFamily: 'OpenRundeSemibold', fontSize: 15 },
  secondary: { marginTop: 12, paddingHorizontal: 16, paddingVertical: 10 },
  secondaryText: { fontFamily: 'OpenRundeSemibold', fontSize: 14 },
  status: { alignItems: 'center', flex: 1, justifyContent: 'center', paddingHorizontal: 24 },
  statusText: { fontFamily: 'OpenRundeMedium', fontSize: 16, marginTop: 16, textAlign: 'center' },
});
