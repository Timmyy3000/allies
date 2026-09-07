import { describe, expect, it } from 'vitest';

import appConfig from './app.json';
import { getNativeLinkConfig } from './app.config';

describe('mobile app config', () => {
  it('uses the next native runtime for the splash-screen build', () => {
    expect(appConfig.expo.version).toBe('1.0.4');
  });

  it('uses the Allies brand for the native splash screen', () => {
    const splashPlugin = appConfig.expo.plugins.find(
      (plugin) => Array.isArray(plugin) && plugin[0] === 'expo-splash-screen',
    );

    expect(splashPlugin).toEqual([
      'expo-splash-screen',
      {
        backgroundColor: '#FF5800',
        image: './assets/allies/icons/allies-app-icon.png',
        imageWidth: 180,
        resizeMode: 'contain',
      },
    ]);
  });

  it('configures photo access without requesting camera or microphone permissions', () => {
    const imagePickerPlugin = appConfig.expo.plugins.find(
      (plugin) => Array.isArray(plugin) && plugin[0] === 'expo-image-picker',
    );

    expect(imagePickerPlugin).toEqual([
      'expo-image-picker',
      {
        cameraPermission: false,
        microphonePermission: false,
        photosPermission: 'Allow Allies to use your photos for your profile avatar.',
      },
    ]);
  });

  it('does not claim an app link until the exact registered return URL is configured', () => {
    expect(getNativeLinkConfig(undefined)).toEqual({});
  });
});
