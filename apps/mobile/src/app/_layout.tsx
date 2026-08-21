import { useFonts } from 'expo-font';
import { DarkTheme, DefaultTheme, Stack, ThemeProvider, usePathname, useRouter } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { useEffect } from 'react';
import { useColorScheme } from 'react-native';

import { KeyboardDismissView } from '@/components/ui/keyboard-dismiss-view';
import { AppProviders } from '@/lib/providers/app-providers';
import { useNativeSession } from '@/lib/session/session-context';

SplashScreen.preventAutoHideAsync();
SplashScreen.setOptions({ duration: 350, fade: true });

export default function RootLayout() {
  const colorScheme = useColorScheme();
  const [fontsLoaded] = useFonts({
    OpenRundeMedium: require('@/assets/allies/fonts/OpenRunde-Medium.otf'),
    OpenRundeSemibold: require('@/assets/allies/fonts/OpenRunde-Semibold.otf'),
  });

  useEffect(() => {
    if (fontsLoaded) SplashScreen.hide();
  }, [fontsLoaded]);

  if (!fontsLoaded) return null;

  return (
    <AppProviders>
      <ThemeProvider value={colorScheme === 'dark' ? DarkTheme : DefaultTheme}>
        <KeyboardDismissView style={{ flex: 1 }}>
          <SessionRouteRedirector />
          <Stack screenOptions={{ headerShown: false }} />
        </KeyboardDismissView>
      </ThemeProvider>
    </AppProviders>
  );
}

function SessionRouteRedirector() {
  const pathname = usePathname();
  const router = useRouter();
  const session = useNativeSession();

  useEffect(() => {
    if (session.status === 'signed-in' && pathname !== '/account') {
      router.replace('/account');
    } else if (session.status === 'signed-out' && pathname === '/account') {
      router.replace('/sign-in');
    }
  }, [pathname, router, session.status]);

  return null;
}
