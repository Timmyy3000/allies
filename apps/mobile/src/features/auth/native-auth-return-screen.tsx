import { useRouter } from 'expo-router';
import * as Linking from 'expo-linking';
import { useEffect, useRef, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { PrimaryButton } from '@/components/ui/primary-button';
import { useTheme } from '@/hooks/use-theme';
import { useNativeSession } from '@/lib/session/session-context';
import { selectMobileReturnTo } from '@/lib/session/session-route';

import { deliverNativeAuthReturn } from './native-auth-return';

export default function NativeAuthReturnScreen() {
  const router = useRouter();
  const theme = useTheme();
  const session = useNativeSession();
  const url = Linking.useURL();
  const handledRef = useRef(false);
  const navigatedRef = useRef(false);
  const [handled, setHandled] = useState<boolean | null>(null);
  const signInFailed = handled === false
    || (handled === true && session.googleSignInOutcome !== null && session.googleSignInOutcome.status !== 'signed-in');

  useEffect(() => {
    if (!url || handledRef.current) return;
    handledRef.current = true;
    setHandled(deliverNativeAuthReturn(url));
  }, [url]);

  useEffect(() => {
    if (navigatedRef.current || session.status !== 'signed-in') return;
    if (handled !== true && session.googleSignInStatus !== 'idle') return;
    navigatedRef.current = true;
    const target = selectMobileReturnTo(session.googleSignInReturnTo);
    session.clearGoogleSignInReturnTo();
    router.replace(target as never);
  }, [handled, router, session]);

  const retry = () => {
    const target = selectMobileReturnTo(session.googleSignInReturnTo);
    router.replace(`/sign-in?returnTo=${encodeURIComponent(target)}` as never);
  };

  return (
    <View style={[styles.root, { backgroundColor: theme.appBackground }]}>
      <SafeAreaView style={styles.safeArea}>
        <View style={styles.content}>
          <Text style={[styles.title, { color: theme.primaryText }]}>
            {signInFailed ? 'Sign-in needs a retry' : handled === true ? 'Finishing sign-in…' : 'Returning to Allies…'}
          </Text>
          <Text style={[styles.subtitle, { color: theme.supportingText }]}>
            {signInFailed
              ? 'This sign-in session is no longer available. Start again to continue.'
              : handled === true
                ? 'Your sign-in is being completed securely.'
                : 'Your secure sign-in is being completed.'}
          </Text>
          {signInFailed ? <PrimaryButton label="Return to sign in" onPress={retry} /> : null}
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
    padding: 24,
  },
  root: {
    flex: 1,
  },
  safeArea: {
    flex: 1,
  },
  subtitle: {
    fontFamily: 'OpenRundeMedium',
    fontSize: 16,
    lineHeight: 22,
    marginBottom: 24,
    marginTop: 12,
    textAlign: 'center',
  },
  title: {
    fontFamily: 'OpenRundeSemibold',
    fontSize: 24,
    lineHeight: 29,
    textAlign: 'center',
  },
});
