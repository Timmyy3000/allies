import { useFonts } from 'expo-font';
import {
  DarkTheme,
  DefaultTheme,
  Stack,
  ThemeProvider,
  useGlobalSearchParams,
  usePathname,
  useRouter,
} from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { useEffect } from 'react';
import { useColorScheme } from 'react-native';

import { KeyboardDismissView } from '@/components/ui/keyboard-dismiss-view';
import { useMockApp } from '@/features/mock/mock-app';
import { AppProviders } from '@/lib/providers/app-providers';
import { useNativeSession } from '@/lib/session/session-context';
import { getSessionRouteAction } from '@/lib/session/session-route';

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
  const mock = useMockApp();
  const pathname = usePathname();
  const { returnTo } = useGlobalSearchParams<{ returnTo?: string }>();
  const router = useRouter();
  const session = useNativeSession();
  const action = getSessionRouteAction(session.status, pathname, returnTo);

  useEffect(() => {
    if (mock.isMock) return;
    if (action) router.replace(action.path as never);
  }, [action, mock.isMock, router]);

  if (mock.isMock) return null;

  return null;
}
