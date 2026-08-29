import { SymbolView } from 'expo-symbols';
import { StatusBar } from 'expo-status-bar';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { PrimaryButton } from '@/components/ui/primary-button';
import { useMockApp } from '@/features/mock/mock-app';
import { AlliesLogo } from '@/features/onboarding/allies-logo';

import { useGoogleSignIn } from './use-google-sign-in';

type AccountAccessMode = 'sign-in' | 'create-account';

export function AccountAccessScreen({ mode }: { mode: AccountAccessMode }) {
  const router = useRouter();
  const { returnTo } = useLocalSearchParams<{ returnTo?: string }>();
  const mock = useMockApp();
  const signIn = useGoogleSignIn();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [passwordConfirmation, setPasswordConfirmation] = useState('');
  const isCreateAccount = mode === 'create-account';
  const returnQuery = typeof returnTo === 'string' ? `?returnTo=${encodeURIComponent(returnTo)}` : '';
  const switchHref = `${isCreateAccount ? '/sign-in' : '/create-account'}${returnQuery}`;
  const credentialsReady = username.trim().length > 0
    && password.length > 0
    && (!isCreateAccount || password === passwordConfirmation);
  const message = mock.isMock ? null : signIn.outcome?.status === 'canceled'
    ? 'Google sign-in was canceled.'
    : signIn.outcome?.status === 'failed'
      ? signIn.outcome.reason === 'unavailable'
        ? 'Google access is temporarily unavailable.'
        : signIn.outcome.reason === 'invalid-return'
          ? 'That Google sign-in link was no longer valid. Try again.'
          : 'We could not finish Google access. Try again.'
      : null;
  const completeAccess = () => {
    mock.signIn();
    router.replace((typeof returnTo === 'string' ? returnTo : '/allies') as never);
  };

  return (
    <View style={styles.root}>
      <StatusBar style="dark" />
      <SafeAreaView edges={['top', 'bottom']} style={styles.safeArea}>
        <ScrollView
          contentContainerStyle={styles.scrollContent}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}>
          <View style={styles.topRow}>
            <Pressable
              accessibilityLabel="Go back"
              accessibilityRole="button"
              onPress={() => router.back()}
              style={({ pressed }) => [styles.backButton, pressed && styles.pressed]}>
              <SymbolView
                name={{ ios: 'chevron.left', android: 'chevron_left', web: 'chevron_left' }}
                size={20}
                tintColor="#111111"
                weight="semibold"
              />
            </Pressable>
            <AlliesLogo height={42} width={49} />
          </View>

          <View style={styles.header}>
            <Text style={styles.title}>{isCreateAccount ? 'Create your account' : 'Welcome back'}</Text>
            <Text style={styles.subtitle}>
              {isCreateAccount
                ? 'Choose Google or create an Allies username.'
                : 'Sign in with Google or your Allies username.'}
            </Text>
          </View>

          <View style={styles.form}>
            {message ? <Text style={styles.message}>{message}</Text> : null}
            {!mock.isMock && !signIn.isAvailable ? (
              <Text style={styles.configurationMessage}>
                Google access will be available once this build has its registered app return link.
              </Text>
            ) : null}
            <PrimaryButton
              bottomMargin={20}
              disabled={!mock.isMock && (!signIn.isAvailable || signIn.isBusy)}
              label={signIn.isBusy
                ? 'Opening Google…'
                : isCreateAccount
                  ? 'Create account with Google'
                  : 'Sign in with Google'}
              onPress={() => {
                if (mock.isMock) {
                  completeAccess();
                  return;
                }
                void signIn.start();
              }}
            />

            <View style={styles.dividerRow}>
              <View style={styles.divider} />
              <Text style={styles.dividerText}>or</Text>
              <View style={styles.divider} />
            </View>

            <Text style={styles.label}>Username</Text>
            <TextInput
              accessibilityLabel="Username"
              autoCapitalize="none"
              autoComplete="username"
              autoCorrect={false}
              maxLength={64}
              onChangeText={setUsername}
              placeholder="Your username"
              placeholderTextColor="#999999"
              style={styles.input}
              value={username}
            />

            <Text style={styles.label}>Password</Text>
            <TextInput
              accessibilityLabel="Password"
              autoCapitalize="none"
              autoComplete={isCreateAccount ? 'new-password' : 'current-password'}
              maxLength={128}
              onChangeText={setPassword}
              placeholder="Your password"
              placeholderTextColor="#999999"
              secureTextEntry
              style={styles.input}
              value={password}
            />

            {isCreateAccount ? (
              <>
                <Text style={styles.label}>Confirm password</Text>
                <TextInput
                  accessibilityLabel="Confirm password"
                  autoCapitalize="none"
                  autoComplete="new-password"
                  maxLength={128}
                  onChangeText={setPasswordConfirmation}
                  placeholder="Enter your password again"
                  placeholderTextColor="#999999"
                  secureTextEntry
                  style={styles.input}
                  value={passwordConfirmation}
                />
              </>
            ) : null}

            <PrimaryButton
              bottomMargin={20}
              disabled={!credentialsReady}
              label={isCreateAccount ? 'Create account' : 'Sign in'}
              onPress={completeAccess}
            />

            <View style={styles.switchRow}>
              <Text style={styles.switchPrompt}>{isCreateAccount ? 'Already have an account?' : 'New to Allies?'}</Text>
              <Pressable
                accessibilityRole="link"
                onPress={() => router.replace(switchHref as never)}
                style={({ pressed }) => pressed && styles.pressed}>
                <Text style={styles.switchLink}>{isCreateAccount ? 'Sign in' : 'Create an account'}</Text>
              </Pressable>
            </View>
          </View>
        </ScrollView>
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  backButton: {
    alignItems: 'center',
    backgroundColor: '#F3F3F3',
    borderRadius: 20,
    height: 40,
    justifyContent: 'center',
    width: 40,
  },
  configurationMessage: {
    color: '#7A7A7A',
    fontFamily: 'OpenRundeMedium',
    fontSize: 14,
    lineHeight: 19,
    marginBottom: 16,
    textAlign: 'center',
  },
  divider: { backgroundColor: '#E5E5E5', flex: 1, height: 1 },
  dividerRow: { alignItems: 'center', flexDirection: 'row', gap: 12, marginBottom: 20 },
  dividerText: { color: '#8A8A8A', fontFamily: 'OpenRundeMedium', fontSize: 14 },
  form: { marginTop: 34 },
  header: { marginTop: 36 },
  input: {
    backgroundColor: '#F3F3F3',
    borderRadius: 18,
    color: '#111111',
    fontFamily: 'OpenRundeMedium',
    fontSize: 16,
    height: 56,
    lineHeight: 22,
    marginBottom: 18,
    paddingHorizontal: 18,
  },
  label: {
    color: '#111111',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 14,
    lineHeight: 19,
    marginBottom: 8,
  },
  message: {
    color: '#111111',
    fontFamily: 'OpenRundeMedium',
    fontSize: 14,
    lineHeight: 19,
    marginBottom: 16,
    textAlign: 'center',
  },
  pressed: { opacity: 0.72 },
  root: { backgroundColor: '#FFFFFF', flex: 1 },
  safeArea: { flex: 1 },
  scrollContent: { flexGrow: 1, paddingBottom: 34, paddingHorizontal: 20 },
  subtitle: {
    color: '#606060',
    fontFamily: 'OpenRundeMedium',
    fontSize: 16,
    lineHeight: 22,
    marginTop: 10,
  },
  switchLink: { color: '#FF5800', fontFamily: 'OpenRundeSemibold', fontSize: 15 },
  switchPrompt: { color: '#606060', fontFamily: 'OpenRundeMedium', fontSize: 15 },
  switchRow: { alignItems: 'center', flexDirection: 'row', gap: 6, justifyContent: 'center' },
  title: {
    color: '#111111',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 34,
    letterSpacing: -1.4,
    lineHeight: 39,
  },
  topRow: {
    alignItems: 'center',
    flexDirection: 'row',
    justifyContent: 'space-between',
    minHeight: 74,
  },
});
