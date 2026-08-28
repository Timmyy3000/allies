import { isCloudError } from '@allies/cloud-client';
import { useRouter } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { AlliesLogo } from '@/features/onboarding/allies-logo';
import { pendingCommandStore } from '@/lib/pending-command-store';
import { useNativeSession } from '@/lib/session/session-context';

function isTransient(error: unknown): boolean {
  return isCloudError(error) && ['network', 'timeout', 'server', 'throttled'].includes(error.kind);
}

function isInvalidAttempt(error: unknown): boolean {
  return isCloudError(error) && ['bad-request', 'not-found', 'validation'].includes(error.kind);
}

export default function CompleteAllyCreationScreen() {
  const router = useRouter();
  const session = useNativeSession();
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(true);
  const [message, setMessage] = useState('Finishing your Ally…');

  useEffect(() => {
    if (session.status !== 'signed-in' || !session.account || !session.accountClient || !session.adapter) return;

    const controller = new AbortController();
    const { account, accountClient, adapter } = session;

    void (async () => {
      const command = await pendingCommandStore.bindCreate(account.userId, account.workspace.id);
      if (!command) {
        setMessage('There is no pending Ally creation for this session.');
        setBusy(false);
        return;
      }

      try {
        const ally = await adapter.withRefresh(() => accountClient.createAlly(
          account.workspace.id,
          command,
          command.idempotencyKey,
          controller.signal,
        ));
        await pendingCommandStore.deleteCreate();
        router.replace(`/allies/${ally.id}` as never);
      } catch (error) {
        if (isInvalidAttempt(error)) {
          router.replace('/allies/new' as never);
          return;
        }
        setMessage(isTransient(error)
          ? 'We could not confirm the creation. Try again.'
          : 'We could not finish creating your Ally. Try again.');
      } finally {
        if (!controller.signal.aborted) setBusy(false);
      }
    })();

    return () => controller.abort();
  }, [attempt, router, session]);

  const displayMessage = session.status === 'offline-with-session'
    ? 'You are offline. Reconnect to finish creating your Ally.'
    : session.status === 'unavailable'
      ? 'Your session is unavailable on this device.'
      : message;

  return (
    <View style={styles.root}>
      <StatusBar style="dark" />
      <SafeAreaView edges={['top', 'bottom']} style={styles.safeArea}>
        <View style={styles.content}>
          <AlliesLogo height={84} width={98} />
          <ActivityIndicator color="#FF5800" size="small" />
          <Text style={styles.title}>{displayMessage}</Text>
          {session.status === 'signed-in' && !busy ? (
            <Pressable
              accessibilityRole="button"
              onPress={() => {
                setBusy(true);
                setAttempt((value) => value + 1);
              }}
              style={styles.retry}>
              <Text style={styles.retryText}>Try again</Text>
            </Pressable>
          ) : null}
          <Pressable accessibilityRole="button" onPress={() => router.replace('/allies' as never)} style={styles.secondary}>
            <Text style={styles.secondaryText}>Back to Allies</Text>
          </Pressable>
        </View>
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  content: {
    alignItems: 'center',
    flex: 1,
    justifyContent: 'center',
    paddingHorizontal: 28,
  },
  retry: {
    backgroundColor: '#FF5800',
    borderRadius: 999,
    marginTop: 24,
    paddingHorizontal: 24,
    paddingVertical: 13,
  },
  retryText: {
    color: '#FFFFFF',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 15,
  },
  root: {
    backgroundColor: '#FFFFFF',
    flex: 1,
  },
  safeArea: {
    flex: 1,
  },
  secondary: {
    marginTop: 16,
    paddingHorizontal: 16,
    paddingVertical: 10,
  },
  secondaryText: {
    color: '#606060',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 14,
  },
  title: {
    color: '#111111',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 22,
    lineHeight: 28,
    marginTop: 22,
    textAlign: 'center',
  },
});
