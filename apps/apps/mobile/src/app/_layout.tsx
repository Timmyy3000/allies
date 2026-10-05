import { useFonts } from 'expo-font';
import Constants from 'expo-constants';
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
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { useColorScheme } from 'react-native';
import { KeyboardProvider } from 'react-native-keyboard-controller';

import { KeyboardDismissView } from '@/components/ui/keyboard-dismiss-view';
import { LiquidGlassModeProvider } from '@/components/ui/liquid-glass-mode';
import { AppProviders } from '@/lib/providers/app-providers';
import { useNativeSession } from '@/lib/session/session-context';
import { getSessionRouteAction } from '@/lib/session/session-route';

SplashScreen.preventAutoHideAsync();
if (Constants.appOwnership !== 'expo') SplashScreen.setOptions({ duration: 350, fade: true });

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
    <KeyboardProvider>
      <AppProviders>
        <LiquidGlassModeProvider>
          <ThemeProvider value={colorScheme === 'dark' ? DarkTheme : DefaultTheme}>
            <KeyboardDismissView style={{ flex: 1 }}>
              <StatusBar style={colorScheme === 'dark' ? 'light' : 'dark'} />
              <SessionRouteRedirector />
              <Stack screenOptions={{ headerShown: false }} />
            </KeyboardDismissView>
          </ThemeProvider>
        </LiquidGlassModeProvider>
      </AppProviders>
    </KeyboardProvider>
  );
}

function SessionRouteRedirector() {
  const pathname = usePathname();
  const { returnTo } = useGlobalSearchParams<{ returnTo?: string }>();
  const router = useRouter();
  const session = useNativeSession();
  const action = getSessionRouteAction(session.status, pathname, returnTo);
  const authConfigured = session.client !== null;
  const actionPath = action?.path ?? null;

  useEffect(() => {
    if (!authConfigured || !actionPath) return;
    router.replace(actionPath as never);
  }, [actionPath, authConfigured, router]);

  return null;
}
