import { useQuery } from '@tanstack/react-query';
import { StatusBar } from 'expo-status-bar';
import { useIsFocused, useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { AlliesLogo } from '@/features/onboarding/allies-logo';
import { OnboardingAllyPreview } from '@/features/onboarding/onboarding-ally-preview';
import { getAllyAppearance } from '@/features/allies/ally-appearance';
import { useAllySessionIndex } from '@/features/allies/ally-session-index';
import { pendingCommandStore } from '@/lib/pending-command-store';
import { useNativeSession } from '@/lib/session/session-context';

const PAGE_SIZE = 12;

function AllyCard({ allyId }: { allyId: string }) {
  const router = useRouter();
  const session = useNativeSession();
  const { addReachableAllyId } = useAllySessionIndex();
  const workspaceId = session.status === 'signed-in' && session.account ? session.account.workspace.id : '';
  const query = useQuery({
    queryKey: ['allies', workspaceId, allyId],
    enabled: Boolean(workspaceId && session.accountClient && session.adapter),
    queryFn: ({ signal }) => session.adapter!.withRefresh(() => session.accountClient!.getAlly(workspaceId, allyId, signal)),
  });

  if (query.isPending) {
    return <View style={styles.card}><ActivityIndicator color="#FF5800" /></View>;
  }

  if (query.isError || !query.data) {
    return (
      <View style={styles.card}>
        <Text style={styles.errorText}>We could not load this Ally.</Text>
        <Pressable accessibilityRole="button" onPress={() => void query.refetch()}>
          <Text style={styles.retryText}>Try again</Text>
        </Pressable>
      </View>
    );
  }

  const appearance = getAllyAppearance(query.data.appearance.key);
  return (
    <Pressable
      accessibilityLabel={`Open ${query.data.name}`}
      accessibilityRole="button"
      onPress={() => {
        addReachableAllyId(allyId);
        router.push(`/allies/${allyId}` as never);
      }}
      style={({ pressed }) => [styles.card, pressed && styles.cardPressed]}>
      <OnboardingAllyPreview
        accessibilityLabel={`${query.data.name} Ally`}
        color={appearance.color}
        identity={appearance.shape}
        size={68}
      />
      <View style={styles.cardCopy}>
        <Text numberOfLines={1} style={styles.allyName}>{query.data.name}</Text>
        <Text numberOfLines={2} style={styles.allyJob}>{query.data.job}</Text>
        <Text style={styles.state}>
          {query.data.provisioningState}{query.data.retryable ? ' · retry available' : ''}
        </Text>
      </View>
    </Pressable>
  );
}

export default function AlliesScreen() {
  const router = useRouter();
  const focused = useIsFocused();
  const session = useNativeSession();
  const { reachableAllyIds } = useAllySessionIndex();
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const [pendingCreateName, setPendingCreateName] = useState<string | null>(null);
  const visibleIds = reachableAllyIds.slice(0, visibleCount);

  useEffect(() => {
    if (!focused || session.status !== 'signed-in' || !session.account) return;
    let active = true;
    void pendingCommandStore.readCreate(session.account.userId, session.account.workspace.id).then((command) => {
      if (active) setPendingCreateName(command?.name ?? null);
    });
    return () => {
      active = false;
    };
  }, [focused, session.account, session.status]);

  return (
    <View style={styles.root}>
      <StatusBar style="dark" />
      <SafeAreaView edges={['top', 'bottom']} style={styles.safeArea}>
        <View style={styles.header}>
          <AlliesLogo height={48} width={56} />
          <View style={styles.headerActions}>
            <Pressable accessibilityLabel="Create a new Ally" accessibilityRole="button" onPress={() => router.push('/allies/new' as never)}>
              <Text style={styles.headerAction}>New Ally</Text>
            </Pressable>
            <Pressable accessibilityLabel="Open account" accessibilityRole="button" onPress={() => router.push('/account')}>
              <Text style={styles.headerAction}>Account</Text>
            </Pressable>
          </View>
        </View>

        <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
          <Text style={styles.title}>Your Allies</Text>
          <Text style={styles.subtitle}>Open an Ally to continue where you left off.</Text>

          {session.status === 'offline-with-session' ? (
            <Text style={styles.notice}>You are offline. Reconnect to load your session Allies.</Text>
          ) : null}

          {pendingCreateName ? (
            <Pressable
              accessibilityLabel={`Finish creating ${pendingCreateName}`}
              accessibilityRole="button"
              onPress={() => router.push('/allies/new/complete' as never)}
              style={styles.pendingCard}>
              <Text style={styles.pendingTitle}>Finish creating {pendingCreateName}</Text>
              <Text style={styles.pendingText}>Your saved reply is ready to continue.</Text>
            </Pressable>
          ) : null}

          {visibleIds.length ? visibleIds.map((allyId) => <AllyCard allyId={allyId} key={allyId} />) : (
            <View style={styles.emptyState}>
              <Text style={styles.emptyTitle}>No reachable Allies yet</Text>
              <Text style={styles.emptyText}>
                This first mobile slice keeps a session-scoped list of Allies you create or open. Full workspace restoration is not yet available.
              </Text>
              <Pressable accessibilityRole="button" onPress={() => router.push('/allies/new' as never)} style={styles.primaryAction}>
                <Text style={styles.primaryActionText}>Create your first Ally</Text>
              </Pressable>
            </View>
          )}

          {visibleCount < reachableAllyIds.length ? (
            <Pressable accessibilityRole="button" onPress={() => setVisibleCount((count) => count + PAGE_SIZE)} style={styles.loadMore}>
              <Text style={styles.loadMoreText}>Load more</Text>
            </Pressable>
          ) : null}
        </ScrollView>
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  allyJob: {
    color: '#606060',
    fontFamily: 'OpenRundeMedium',
    fontSize: 15,
    lineHeight: 20,
    marginTop: 3,
  },
  allyName: {
    color: '#111111',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 19,
    lineHeight: 23,
  },
  card: {
    alignItems: 'center',
    backgroundColor: '#F7F7F7',
    borderRadius: 24,
    flexDirection: 'row',
    marginTop: 14,
    minHeight: 108,
    paddingHorizontal: 16,
    paddingVertical: 16,
  },
  cardCopy: {
    flex: 1,
    marginLeft: 14,
  },
  cardPressed: {
    opacity: 0.82,
  },
  content: {
    paddingBottom: 32,
    paddingHorizontal: 20,
  },
  emptyState: {
    alignItems: 'center',
    backgroundColor: '#F7F7F7',
    borderRadius: 24,
    marginTop: 28,
    paddingHorizontal: 24,
    paddingVertical: 32,
  },
  emptyText: {
    color: '#606060',
    fontFamily: 'OpenRundeMedium',
    fontSize: 15,
    lineHeight: 21,
    marginTop: 10,
    textAlign: 'center',
  },
  emptyTitle: {
    color: '#111111',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 20,
    lineHeight: 24,
    textAlign: 'center',
  },
  errorText: {
    color: '#606060',
    flex: 1,
    fontFamily: 'OpenRundeMedium',
    fontSize: 15,
  },
  header: {
    alignItems: 'center',
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingHorizontal: 20,
    paddingVertical: 14,
  },
  headerAction: {
    color: '#FF5800',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 14,
  },
  headerActions: {
    alignItems: 'center',
    flexDirection: 'row',
    gap: 16,
  },
  loadMore: {
    alignItems: 'center',
    borderColor: '#D6D6D6',
    borderRadius: 999,
    borderWidth: 1,
    marginTop: 18,
    paddingHorizontal: 22,
    paddingVertical: 12,
  },
  loadMoreText: {
    color: '#111111',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 15,
  },
  notice: {
    color: '#7A7A7A',
    fontFamily: 'OpenRundeMedium',
    fontSize: 14,
    lineHeight: 19,
    marginTop: 18,
  },
  pendingCard: {
    backgroundColor: '#FFF0E8',
    borderRadius: 20,
    marginTop: 18,
    paddingHorizontal: 18,
    paddingVertical: 16,
  },
  pendingText: {
    color: '#606060',
    fontFamily: 'OpenRundeMedium',
    fontSize: 14,
    lineHeight: 19,
    marginTop: 4,
  },
  pendingTitle: {
    color: '#111111',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 16,
    lineHeight: 20,
  },
  primaryAction: {
    backgroundColor: '#FF5800',
    borderRadius: 999,
    marginTop: 22,
    paddingHorizontal: 20,
    paddingVertical: 13,
  },
  primaryActionText: {
    color: '#FFFFFF',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 15,
  },
  root: {
    backgroundColor: '#FFFFFF',
    flex: 1,
  },
  retryText: {
    color: '#FF5800',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 14,
  },
  safeArea: {
    flex: 1,
  },
  state: {
    color: '#8A8A8A',
    fontFamily: 'OpenRundeMedium',
    fontSize: 12,
    marginTop: 8,
    textTransform: 'capitalize',
  },
  subtitle: {
    color: '#606060',
    fontFamily: 'OpenRundeMedium',
    fontSize: 16,
    lineHeight: 22,
    marginTop: 8,
  },
  title: {
    color: '#111111',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 32,
    letterSpacing: -1,
    lineHeight: 38,
    marginTop: 10,
  },
});
