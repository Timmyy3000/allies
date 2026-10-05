import { isCloudError } from '@allies/cloud-client';
import { useRouter } from 'expo-router';
import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { allyKeys } from '@/features/allies/queries';
import { OnboardingAllyPreview } from '@/features/onboarding/onboarding-ally-preview';
import { pendingCommandStore, toCloudCreateAllyInput } from '@/lib/pending-command-store';
import { useNativeSession } from '@/lib/session/session-context';
import { useTheme } from '@/hooks/use-theme';

function isTransient(error: unknown): boolean {
  return isCloudError(error) && ['network', 'timeout', 'server', 'throttled'].includes(error.kind);
}

function isInvalidAttempt(error: unknown): boolean {
  return isCloudError(error) && ['bad-request', 'not-found', 'validation'].includes(error.kind);
}

export default function CompleteAllyCreationScreen() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const theme = useTheme();
  const session = useNativeSession();
  const { account, accountClient, adapter, status } = session;
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(true);
  const [message, setMessage] = useState('Finishing your Ally…');
  const runRef = useRef(0);
  const sessionIdentityRef = useRef<string | null>(null);

  useEffect(() => {
    sessionIdentityRef.current = status === 'signed-in' && account
      ? `${account.userId}:${account.workspace.id}`
      : null;
  }, [account, status]);

  useEffect(() => {
    if (status !== 'signed-in' || !account || !accountClient || !adapter) return;

    const run = ++runRef.current;
    const controller = new AbortController();
    const workspaceId = account.workspace.id;
    const capturedIdentity = sessionIdentityRef.current;
    const isCurrent = () => run === runRef.current
      && !controller.signal.aborted
      && sessionIdentityRef.current === capturedIdentity;

    void (async () => {
      try {
        const command = await pendingCommandStore.bindCreate(account.userId, workspaceId);
        if (!isCurrent()) return;
        if (!command) {
          setMessage('There is no pending Ally creation for this session.');
          setBusy(false);
          return;
        }

        const ally = await adapter.withRefresh(() => accountClient.createAlly(
          workspaceId,
          toCloudCreateAllyInput(command),
          command.idempotencyKey,
          controller.signal,
        ));
        if (!isCurrent()) return;
        try {
          await pendingCommandStore.deleteCreate();
        } catch {
          // Cloud accepted the idempotent command; a later retry can reconcile local cleanup.
        }
        if (!isCurrent()) return;
        queryClient.setQueryData(allyKeys.detail(workspaceId, ally.id), ally);
        void queryClient.invalidateQueries({ queryKey: allyKeys.all(workspaceId) }).catch(() => undefined);
        router.replace(`/allies/new/post-setup?allyId=${encodeURIComponent(ally.id)}` as never);
      } catch (error) {
        if (!isCurrent()) return;
        if (isInvalidAttempt(error)) {
          router.replace('/allies/new' as never);
          return;
        }
        setMessage(isTransient(error)
          ? 'We could not confirm the creation. Try again.'
          : 'We could not finish creating your Ally. Try again.');
      } finally {
        if (isCurrent()) setBusy(false);
      }
    })();

    return () => {
      controller.abort();
      runRef.current += 1;
    };
  }, [account, accountClient, adapter, attempt, queryClient, router, status]);

  const retry = () => {
    setBusy(true);
    setMessage('Finishing your Ally…');
    setAttempt((value) => value + 1);
  };

  return (
    <View style={[styles.root, { backgroundColor: theme.appBackground }]}>
      <SafeAreaView edges={['top', 'bottom']} style={styles.safeArea}>
        <View style={styles.content}>
          {busy ? <OnboardingAllyPreview accessibilityLabel="Ally getting ready" color="#FF7A00" identity="boxy" size={92} state="thinking" /> : null}
          <Text style={[styles.title, { color: theme.primaryText }]}>{message}</Text>
          {!busy && session.status === 'signed-in' ? (
            <Pressable accessibilityRole="button" onPress={retry} style={[styles.retry, { backgroundColor: theme.primaryText }]}>
              <Text style={[styles.retryText, { color: theme.appBackground }]}>Try again</Text>
            </Pressable>
          ) : null}
          <Pressable accessibilityRole="button" onPress={() => router.replace('/allies' as never)} style={styles.secondary}>
            <Text style={[styles.secondaryText, { color: theme.supportingText }]}>Back to Allies</Text>
          </Pressable>
        </View>
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  content: { alignItems: 'center', flex: 1, justifyContent: 'center', paddingHorizontal: 28 },
  retry: { borderRadius: 999, marginTop: 24, paddingHorizontal: 24, paddingVertical: 13 },
  retryText: { fontFamily: 'OpenRundeSemibold', fontSize: 15 },
  root: { flex: 1 },
  safeArea: { flex: 1 },
  secondary: { marginTop: 16, paddingHorizontal: 16, paddingVertical: 10 },
  secondaryText: { fontFamily: 'OpenRundeSemibold', fontSize: 14 },
  title: { fontFamily: 'OpenRundeSemibold', fontSize: 22, lineHeight: 28, marginTop: 22, textAlign: 'center' },
});
