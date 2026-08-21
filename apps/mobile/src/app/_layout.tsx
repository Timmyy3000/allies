import { useFonts } from 'expo-font';
import { DarkTheme, DefaultTheme, Stack, ThemeProvider } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { useEffect } from 'react';
import { useColorScheme } from 'react-native';

import { KeyboardDismissView } from '@/components/ui/keyboard-dismiss-view';
import { AppProviders } from '@/lib/providers/app-providers';

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
          <Stack screenOptions={{ headerShown: false }} />
        </KeyboardDismissView>
      </ThemeProvider>
    </AppProviders>
  );
}
