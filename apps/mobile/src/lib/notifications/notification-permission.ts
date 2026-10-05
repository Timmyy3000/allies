import Constants from 'expo-constants';
import { Platform } from 'react-native';

const DEFAULT_NOTIFICATION_CHANNEL_ID = 'allies-default';

export async function requestNotificationPermission(): Promise<void> {
  if (Platform.OS === 'android' && Constants.appOwnership === 'expo') return;

  const Notifications = await import('expo-notifications');

  if (Platform.OS === 'android') {
    await Notifications.setNotificationChannelAsync(DEFAULT_NOTIFICATION_CHANNEL_ID, {
      importance: Notifications.AndroidImportance.DEFAULT,
      name: 'Allies',
    });
  }

  await Notifications.requestPermissionsAsync();
}
