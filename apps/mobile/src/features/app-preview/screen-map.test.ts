import { describe, expect, it } from 'vitest';

import { getAllPreviewScreens, getPreviewScreen } from './screen-map';

describe('preview screen map', () => {
  it('keeps every screen addressable and every action inside the app', () => {
    const screens = getAllPreviewScreens();
    const keys = screens.map((screen) => `${screen.family}:${screen.id}`);

    expect(new Set(keys).size).toBe(keys.length);
    expect(new Set(screens.map((screen) => screen.family))).toEqual(
      new Set(['activity', 'settings', 'connection', 'ally']),
    );
    expect(screens.flatMap((screen) => screen.actions ?? []).every((action) => !action.href || action.href.startsWith('/'))).toBe(true);
    expect(getPreviewScreen('settings', 'account-security')?.title).toBe('Account and security');
    expect(getPreviewScreen('activity', 'missing')).toBeNull();
  });
});
