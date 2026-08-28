import { useQuery } from '@tanstack/react-query';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { isCloudError, type AllyViewModel } from '@allies/cloud-client';

import { useAllySessionIndex } from '@/features/allies/ally-session-index';
import { getAllyAppearance } from '@/features/allies/ally-appearance';
import { OnboardingAllyPreview } from '@/features/onboarding/onboarding-ally-preview';
import { useNativeSession } from '@/lib/session/session-context';

function allyIdFromParam(value: string | string[] | undefined): string | null {
  const allyId = Array.isArray(value) ? value[0] : value;
  return allyId?.trim() || null;
}

export default function AllyIdentityScreen() {
  const { allyId: allyIdParam } = useLocalSearchParams<{ allyId?: string }>();
  const allyId = allyIdFromParam(allyIdParam);
  const router = useRouter();
  const session = useNativeSession();
  const { addReachableAllyId } = useAllySessionIndex();
  const workspaceId = session.status === 'signed-in' && session.account ? session.account.workspace.id : '';
  const query = useQuery<AllyViewModel>({
    queryKey: ['allies', workspaceId, allyId],
    enabled: Boolean(allyId && workspaceId && session.accountClient && session.adapter),
    queryFn: ({ signal }) => session.adapter!.withRefresh(() => session.accountClient!.getAlly(workspaceId, allyId!, signal)),
    refetchOnWindowFocus: false,
  });

  useEffect(() => {
    if (query.data && allyId) addReachableAllyId(allyId);
  }, [addReachableAllyId, allyId, query.data]);

  if (!allyId) return <State message="This Ally link is not valid." onBack={() => router.replace('/allies' as never)} />;
  if (session.status === 'offline-with-session' || session.status === 'unavailable') {
    return (
      <State
        message={session.status === 'offline-with-session'
          ? 'You are offline. Reconnect to load this identity.'
          : 'Your session is unavailable on this device.'}
        onBack={() => router.replace('/allies' as never)}
        onRetry={() => void session.restore()}
      />
    );
  }
  if (query.isPending) {
    return (
      <View style={styles.centered}>
        <StatusBar style="dark" />
        <ActivityIndicator color="#FF5800" />
      </View>
    );
  }
  if (query.isError || !query.data) {
    const error = query.error;
    const text = isCloudError(error) && error.kind === 'not-found' ? 'This Ally is no longer available.' : 'We could not load this identity.';
    return <State message={text} onBack={() => router.replace(`/allies/${allyId}` as never)} />;
  }

  const ally = query.data;
  const appearance = getAllyAppearance(ally.appearance.key);
  return (
    <View style={styles.root}>
      <StatusBar style="dark" />
      <SafeAreaView edges={['top', 'bottom']} style={styles.safeArea}>
        <View style={styles.header}>
          <Pressable accessibilityLabel="Back to conversation" accessibilityRole="button" onPress={() => router.replace(`/allies/${allyId}` as never)}>
            <Text style={styles.backText}>Back</Text>
          </Pressable>
          <Text style={styles.headerTitle}>Identity</Text>
          <View style={styles.headerSpacer} />
        </View>
        <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
          <OnboardingAllyPreview accessibilityLabel={`${ally.name} Ally`} color={appearance.color} identity={appearance.shape} size={112} />
          <Text style={styles.name}>{ally.name}</Text>
          <Text style={styles.provisioning}>
            {ally.provisioningState}{ally.retryable ? ' · retry available' : ''}
          </Text>
          <IdentityField label="Job" value={ally.job} />
          <IdentityField label="Personality" value={ally.personality} />
          <IdentityField label="Appearance" value={ally.appearance.key} />
        </ScrollView>
      </SafeAreaView>
    </View>
  );
}

function IdentityField({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.field}>
      <Text style={styles.label}>{label}</Text>
      <Text style={styles.value}>{value}</Text>
    </View>
  );
}

function State({ message, onBack, onRetry }: { message: string; onBack: () => void; onRetry?: () => void }) {
  return (
    <View style={styles.centered}>
      <StatusBar style="dark" />
      <Text style={styles.stateText}>{message}</Text>
      {onRetry ? (
        <Pressable accessibilityRole="button" onPress={onRetry} style={styles.action}>
          <Text style={styles.actionText}>Try again</Text>
        </Pressable>
      ) : null}
      <Pressable accessibilityRole="button" onPress={onBack} style={styles.action}>
        <Text style={styles.actionText}>Back</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  action: {
    backgroundColor: '#FF5800',
    borderRadius: 999,
    marginTop: 22,
    paddingHorizontal: 22,
    paddingVertical: 12,
  },
  actionText: {
    color: '#FFFFFF',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 15,
  },
  backText: {
    color: '#FF5800',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 14,
  },
  centered: {
    alignItems: 'center',
    backgroundColor: '#FFFFFF',
    flex: 1,
    justifyContent: 'center',
    paddingHorizontal: 28,
  },
  content: {
    alignItems: 'center',
    paddingBottom: 32,
    paddingHorizontal: 24,
  },
  field: {
    alignSelf: 'stretch',
    borderBottomColor: '#E4E4E4',
    borderBottomWidth: 1,
    paddingVertical: 16,
  },
  header: {
    alignItems: 'center',
    flexDirection: 'row',
    justifyContent: 'space-between',
    minHeight: 62,
    paddingHorizontal: 20,
  },
  headerSpacer: {
    width: 36,
  },
  headerTitle: {
    color: '#111111',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 17,
  },
  label: {
    color: '#8A8A8A',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 12,
    textTransform: 'uppercase',
  },
  name: {
    color: '#111111',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 28,
    lineHeight: 34,
    marginTop: 16,
  },
  provisioning: {
    color: '#8A8A8A',
    fontFamily: 'OpenRundeMedium',
    fontSize: 13,
    marginTop: 6,
    textTransform: 'capitalize',
  },
  root: {
    backgroundColor: '#FFFFFF',
    flex: 1,
  },
  safeArea: {
    flex: 1,
  },
  stateText: {
    color: '#606060',
    fontFamily: 'OpenRundeMedium',
    fontSize: 16,
    textAlign: 'center',
  },
  value: {
    color: '#111111',
    fontFamily: 'OpenRundeMedium',
    fontSize: 16,
    lineHeight: 22,
    marginTop: 7,
  },
});
