import { useRouter } from 'expo-router';
import { StyleSheet, Text, View } from 'react-native';

import { OnboardingAlliesScreen } from '@/features/onboarding/onboarding-allies-screen';
import { OnboardingAllyPreview } from '@/features/onboarding/onboarding-ally-preview';
import { getAllyAppearance } from '@/features/allies/ally-appearance';
import { formatAllyTime, useAllies, useAllyPreviews } from '@/features/allies/queries';
import { useTheme } from '@/hooks/use-theme';
import { useNativeSession } from '@/lib/session/session-context';

function profileInitials(displayName: string): string {
  const parts = displayName.trim().split(/\s+/u).filter(Boolean);
  return (parts.length > 1 ? `${parts[0][0]}${parts.at(-1)?.[0]}` : parts[0]?.slice(0, 2) ?? 'SD').toUpperCase();
}

export default function AlliesHomeScreen() {
  const router = useRouter();
  const theme = useTheme();
  const session = useNativeSession();
  const alliesQuery = useAllies();
  const workspaceId = session.account?.workspace.id ?? '';
  const previews = useAllyPreviews(workspaceId, alliesQuery.data ?? []);

  if (session.status === 'unavailable' || session.status === 'offline-with-session') {
    return (
      <StatusScreen
        action={{ label: 'Try again', onPress: () => void session.restore() }}
        message={session.status === 'offline-with-session'
          ? 'Reconnect to load your Allies.'
          : 'Your Allies are unavailable on this device.'}
      />
    );
  }

  if (session.status === 'checking' || session.status === 'refreshing' || alliesQuery.isPending) {
    return <StatusScreen busy message="Loading your Allies…" />;
  }

  if (alliesQuery.isError) {
    return <StatusScreen action={{ label: 'Try again', onPress: () => void alliesQuery.refetch() }} message="We could not load your Allies." />;
  }

  const allies = (alliesQuery.data ?? []).map((ally) => {
    const appearance = getAllyAppearance(ally.appearance.key);
    const preview = previews.get(ally.id);
    return {
      color: appearance.color,
      id: ally.id,
      name: ally.name,
      online: ally.provisioningState === 'bound',
      preview: preview?.isPending
        ? 'Loading your latest message…'
        : preview?.latestMessage?.content.replace(/\s+/gu, ' ').trim() || ally.job,
      shape: appearance.shape,
      time: formatAllyTime(preview?.latestMessage?.createdAt),
    };
  });

  return (
    <View style={[styles.root, { backgroundColor: theme.appBackground }]}>
      <OnboardingAlliesScreen
        allies={allies}
        onCreateAlly={() => router.push('/allies/new')}
        onOpenAccount={() => router.push('/account' as never)}
        onOpenAlly={(allyId) => router.push(`/allies/${encodeURIComponent(allyId)}` as never)}
        profileInitials={profileInitials(session.account?.displayName ?? '')}
      />
    </View>
  );
}

function StatusScreen({ action, busy = false, message }: { action?: { label: string; onPress: () => void }; busy?: boolean; message: string }) {
  const theme = useTheme();
  return (
    <View style={[styles.status, { backgroundColor: theme.appBackground }]}>
      {busy ? <OnboardingAllyPreview accessibilityLabel="Allies loading" color="#FF5800" identity="boxy" size={64} state="thinking" /> : null}
      <Text style={[styles.statusMessage, { color: theme.primaryText }]}>{message}</Text>
      {action ? <Text onPress={action.onPress} style={[styles.statusAction, { color: theme.primaryText }]}>{action.label}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  status: { alignItems: 'center', flex: 1, justifyContent: 'center', paddingHorizontal: 28 },
  statusAction: { fontFamily: 'OpenRundeSemibold', fontSize: 16, marginTop: 24 },
  statusMessage: { fontFamily: 'OpenRundeMedium', fontSize: 16, lineHeight: 22, marginTop: 16, textAlign: 'center' },
});
