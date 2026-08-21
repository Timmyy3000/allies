import { useEffect } from 'react';
import { StatusBar } from 'expo-status-bar';
import { useRouter } from 'expo-router';
import { StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { AlliesLogo } from '@/features/onboarding/allies-logo';
import { PrimaryButton } from '@/components/ui/primary-button';
import { useNativeSession } from '@/lib/session/session-context';

import { useGoogleSignIn } from '@/features/auth/use-google-sign-in';

export default function SignInScreen() {
  const router = useRouter();
  const session = useNativeSession();
  const signIn = useGoogleSignIn();

  useEffect(() => {
    if (session.status === 'signed-in') router.replace('/account');
  }, [router, session.status]);

  const message = signIn.outcome?.status === 'canceled'
    ? 'Sign-in canceled.'
    : signIn.outcome?.status === 'failed'
      ? signIn.outcome.reason === 'unavailable'
        ? 'Sign-in is temporarily unavailable.'
        : signIn.outcome.reason === 'invalid-return'
          ? 'That sign-in link was no longer valid. Try again.'
          : 'We could not finish sign-in. Try again.'
      : null;

  return (
    <View style={styles.root}>
      <StatusBar style="dark" />
      <SafeAreaView edges={['top', 'bottom']} style={styles.safeArea}>
        <View style={styles.content}>
          <AlliesLogo height={84} width={98} />
          <Text style={styles.title}>Welcome back</Text>
          <Text style={styles.subtitle}>Sign in to continue with your allies.</Text>
        </View>

        <View style={styles.footer}>
          {message ? <Text style={styles.message}>{message}</Text> : null}
          {!signIn.isAvailable ? (
            <Text style={styles.configurationMessage}>
              Google sign-in will be available once this build has its registered app return link.
            </Text>
          ) : null}
          <PrimaryButton
            disabled={!signIn.isAvailable || signIn.isBusy}
            label={signIn.isBusy ? 'Signing in…' : 'Continue with Google'}
            onPress={() => void signIn.start()}
          />
          <PrimaryButton
            accentColor="#F3F3F3"
            bottomMargin={0}
            label="Back"
            onPress={() => router.back()}
          />
        </View>
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  configurationMessage: {
    color: '#7A7A7A',
    fontFamily: 'OpenRundeMedium',
    fontSize: 14,
    lineHeight: 19,
    marginBottom: 16,
    textAlign: 'center',
  },
  content: {
    alignItems: 'center',
    flex: 1,
    justifyContent: 'center',
    paddingHorizontal: 24,
  },
  footer: {
    paddingHorizontal: 14,
  },
  message: {
    color: '#111111',
    fontFamily: 'OpenRundeMedium',
    fontSize: 14,
    lineHeight: 19,
    marginBottom: 16,
    textAlign: 'center',
  },
  root: {
    backgroundColor: '#FFFFFF',
    flex: 1,
  },
  safeArea: {
    flex: 1,
  },
  subtitle: {
    color: '#606060',
    fontFamily: 'OpenRundeMedium',
    fontSize: 16,
    lineHeight: 22,
    marginTop: 12,
    textAlign: 'center',
  },
  title: {
    color: '#111111',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 28,
    letterSpacing: -1,
    lineHeight: 32,
    marginTop: 32,
  },
});
