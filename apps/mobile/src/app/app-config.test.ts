import { describe, expect, it } from 'vitest';

import appConfig from '../../app.json';

describe('mobile app config', () => {
  it('uses the next native runtime for the splash-screen build', () => {
    expect(appConfig.expo.version).toBe('1.0.1');
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
});
