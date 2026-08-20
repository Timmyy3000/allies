import { DarkTheme, DefaultTheme, Stack, ThemeProvider } from 'expo-router';
import { useColorScheme } from 'react-native';

import { KeyboardDismissView } from '@/components/ui/keyboard-dismiss-view';
import { AppProviders } from '@/lib/providers/app-providers';

export default function RootLayout() {
  const colorScheme = useColorScheme();

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
