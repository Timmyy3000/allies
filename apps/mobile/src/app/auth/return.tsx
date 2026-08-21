import { useRouter } from 'expo-router';
import * as Linking from 'expo-linking';
import { StatusBar } from 'expo-status-bar';
import { useEffect, useRef, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { PrimaryButton } from '@/components/ui/primary-button';

import { deliverNativeAuthReturn } from '@/features/auth/native-auth-return';

export default function AuthReturnScreen() {
  const router = useRouter();
  const url = Linking.useURL();
  const handledRef = useRef(false);
  const [handled, setHandled] = useState<boolean | null>(null);

  useEffect(() => {
    if (!url || handledRef.current) return;
    handledRef.current = true;
    setHandled(deliverNativeAuthReturn(url));
  }, [url]);

  return (
    <View style={styles.root}>
      <StatusBar style="dark" />
      <SafeAreaView style={styles.safeArea}>
        <View style={styles.content}>
          <Text style={styles.title}>{handled ? 'Finishing sign-in…' : 'Sign-in needs a retry'}</Text>
          <Text style={styles.subtitle}>
            {handled
              ? 'Your sign-in is being completed securely.'
              : 'This sign-in session is no longer available. Start again to continue.'}
          </Text>
          <PrimaryButton label="Return to sign in" onPress={() => router.replace('/sign-in')} />
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
    marginBottom: 24,
    marginTop: 12,
    textAlign: 'center',
  },
  title: {
    color: '#111111',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 24,
    lineHeight: 29,
  },
});
