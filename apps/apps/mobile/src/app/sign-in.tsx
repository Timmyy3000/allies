import { useFocusEffect, useLocalSearchParams, useRouter } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ProviderButton } from '@/components/ui/provider-button';
import { LiquidGlassBackground } from '@/components/ui/liquid-glass-background';
import { PrimaryButton } from '@/components/ui/primary-button';
import { useGoogleSignIn } from '@/features/auth/use-google-sign-in';
import { AlliesLogo } from '@/features/onboarding/allies-logo';
import { selectMobileReturnTo } from '@/lib/session/session-route';
import { useNativeSession } from '@/lib/session/session-context';
import { useTheme } from '@/hooks/use-theme';

function errorMessageFor(code: unknown): string | null {
  switch (code) {
    case 'canceled':
      return 'Google sign-in was cancelled.';
    case 'unavailable':
      return 'Google sign-in is temporarily unavailable. Try again.';
    case 'invalid-return':
      return 'That sign-in attempt expired. Start again to continue.';
    case 'flow-failed':
    case 'already-in-progress':
      return 'We couldn\'t complete sign-in securely. Try again.';
    case 'manual-code':
      return 'Enter the sign-in code exactly as shown in your browser.';
    default:
      return null;
  }
}

export default function SignInScreen() {
  const router = useRouter();
  const theme = useTheme();
  const session = useNativeSession();
  const signIn = useGoogleSignIn();
  const mountedRef = useRef(true);
  const { authError, returnTo } = useLocalSearchParams<{ authError?: string; returnTo?: string }>();
  const [dismissedRouteError, setDismissedRouteError] = useState(false);
  const [manualCode, setManualCode] = useState('');
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);
  useFocusEffect(useCallback(() => {
    if (!signIn.isManual) return undefined;
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      setManualCode('');
    };
  }, [signIn.isManual]));
  const sessionPending = session.status === 'checking' || session.status === 'refreshing';
  const missingConfiguration = !session.client || !session.nativeAuthRedirectUri;
  const signInDisabled = signIn.isBusy || !signIn.isAvailable;
  const outcomeError = signIn.outcome?.status === 'canceled'
    ? 'canceled'
    : signIn.outcome?.status === 'failed'
      ? signIn.outcome.reason
      : null;
  const errorMessage = (dismissedRouteError ? null : errorMessageFor(authError))
    ?? (signIn.manualCodeError ? errorMessageFor('manual-code') : null)
    ?? errorMessageFor(outcomeError);

  const handleSignIn = async () => {
    setDismissedRouteError(true);
    setManualCode('');
    const target = selectMobileReturnTo(returnTo);
    const outcome = await signIn.start(target);
    if (!mountedRef.current) return;
    setManualCode('');
    if (outcome.status === 'signed-in') {
      router.replace(target as never);
      return;
    }
    const errorCode = outcome.status === 'canceled' ? 'canceled' : outcome.reason;
    router.replace(`/sign-in?returnTo=${encodeURIComponent(target)}&authError=${encodeURIComponent(errorCode)}` as never);
  };

  const handleManualCode = async () => {
    const outcome = await signIn.submitManualCode(manualCode);
    if (outcome) setManualCode('');
  };

  const manualCodeVisible = signIn.isManual
    && (signIn.status === 'waiting-for-code' || signIn.status === 'exchanging');
  const statusMessage = signIn.status === 'waiting-for-code'
    ? 'Google opened in your browser. Copy the code and paste it here.'
    : signIn.status === 'exchanging'
      ? 'Completing sign-in securely…'
      : signIn.isBusy
        ? 'Opening a secure Google sign-in…'
        : sessionPending
          ? 'Checking your secure session…'
          : missingConfiguration
            ? 'Google sign-in is unavailable in this build.'
            : '';

  return (
    <SafeAreaView style={[styles.root, { backgroundColor: theme.appBackground }]}>
      <View style={styles.content}>
        <AlliesLogo height={78} width={80} />
        <Text style={[styles.title, { color: theme.primaryText }]}>Welcome back</Text>
        <Text style={[styles.subtitle, { color: theme.supportingText }]}>Sign in to continue with your allies.</Text>
      </View>
      <View style={styles.footer}>
        <View style={styles.panel}>
          <ProviderButton
            accessibilityLabel="Continue with Google"
            accessibilityState={{ busy: signIn.isBusy, disabled: signInDisabled }}
            disabled={signInDisabled}
            icon={require('@/assets/allies/icons/google-logo.svg')}
            label={signIn.isBusy ? 'Opening Google…' : 'Continue with Google'}
            onPress={() => void handleSignIn()}
          />
          <Text accessibilityLiveRegion="polite" style={[styles.status, { color: theme.supportingText }]}>
            {statusMessage}
          </Text>
          {manualCodeVisible ? (
            <View style={styles.manualSection}>
              <Text style={[styles.manualHelp, { color: theme.supportingText }]}>Paste the one-time code from the Google browser page.</Text>
              <TextInput
                accessibilityLabel="Sign-in code"
                autoCapitalize="none"
                autoCorrect={false}
                editable={signIn.status !== 'exchanging'}
                onChangeText={setManualCode}
                placeholder="Paste sign-in code"
                placeholderTextColor={theme.supportingText}
                style={[styles.manualInput, { borderColor: theme.supportingText, color: theme.primaryText }]}
                value={manualCode}
              />
              <View style={styles.submitButton}>
                <PrimaryButton
                  accessibilityLabel="Submit sign-in code"
                  accessibilityState={{ busy: signIn.status === 'exchanging', disabled: signIn.status !== 'waiting-for-code' || manualCode.trim().length === 0 }}
                  bottomMargin={0}
                  disabled={signIn.status !== 'waiting-for-code' || manualCode.trim().length === 0}
                  label="Use sign-in code"
                  onPress={() => void handleManualCode()}
                />
              </View>
              <Pressable
                accessibilityLabel="Cancel sign-in"
                accessibilityRole="button"
                onPress={() => { setManualCode(''); void signIn.cancel(); }}
                style={styles.cancelButton}>
                <Text style={[styles.cancelLabel, { color: theme.supportingText }]}>Cancel</Text>
              </Pressable>
            </View>
          ) : null}
          {errorMessage ? (
            <Text accessibilityRole="alert" style={styles.error}>{errorMessage}</Text>
          ) : null}
          <Pressable
            accessibilityRole="button"
            onPress={() => router.back()}
            style={({ pressed }) => [styles.backButton, pressed && styles.backButtonPressed]}>
            <LiquidGlassBackground borderRadius={999} fallbackColor={theme.controlSurface} />
            <Text style={[styles.backButtonLabel, { color: theme.primaryText }]}>Back</Text>
          </Pressable>
        </View>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  backButton: {
    alignItems: 'center',
    borderRadius: 999,
    height: 48,
    justifyContent: 'center',
    marginTop: 12,
    overflow: 'hidden',
    width: '100%',
  },
  backButtonLabel: {
    fontFamily: 'OpenRundeSemibold',
    fontSize: 18,
    includeFontPadding: false,
    letterSpacing: -0.7,
    lineHeight: 18,
  },
  backButtonPressed: {
    opacity: 0.78,
  },
  content: {
    alignItems: 'center',
    flex: 1,
    justifyContent: 'center',
    paddingHorizontal: 24,
    width: '100%',
  },
  error: {
    color: '#B42318',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 13,
    lineHeight: 18,
    marginTop: 8,
    textAlign: 'center',
  },
  footer: {
    paddingHorizontal: 14,
  },
  manualHelp: {
    fontFamily: 'OpenRundeMedium',
    fontSize: 13,
    lineHeight: 18,
    marginBottom: 10,
    textAlign: 'center',
  },
  manualInput: {
    borderRadius: 12,
    borderWidth: 1,
    fontFamily: 'OpenRundeMedium',
    fontSize: 16,
    minHeight: 52,
    paddingHorizontal: 14,
  },
  manualSection: {
    marginTop: 16,
  },
  panel: {
    maxWidth: 420,
    width: '100%',
  },
  root: {
    flex: 1,
  },
  cancelButton: {
    alignItems: 'center',
    minHeight: 44,
    justifyContent: 'center',
    marginTop: 4,
  },
  cancelLabel: {
    fontFamily: 'OpenRundeSemibold',
    fontSize: 14,
    lineHeight: 20,
  },
  status: {
    fontFamily: 'OpenRundeMedium',
    fontSize: 13,
    lineHeight: 18,
    marginTop: 16,
    minHeight: 18,
    textAlign: 'center',
  },
  submitButton: {
    marginTop: 12,
  },
  subtitle: {
    fontFamily: 'OpenRundeMedium',
    fontSize: 16,
    lineHeight: 22,
    marginTop: 12,
    textAlign: 'center',
  },
  title: {
    fontFamily: 'OpenRundeSemibold',
    fontSize: 28,
    includeFontPadding: true,
    letterSpacing: -1,
    lineHeight: 32,
    marginTop: 32,
  },
});
