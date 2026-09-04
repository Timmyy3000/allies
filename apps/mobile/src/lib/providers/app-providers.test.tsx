// @vitest-environment jsdom

import { render, screen } from '@testing-library/react';
import { version as reactVersion } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { useNativeSession } from '../session/session-context';
import { AppProviders } from './app-providers';

vi.mock('expo-secure-store', () => ({
  getItemAsync: vi.fn(async () => null),
  setItemAsync: vi.fn(async () => undefined),
  deleteItemAsync: vi.fn(async () => undefined),
}));

function SessionProbe() {
  const session = useNativeSession();
  return <span>{`${session.status}:${session.reason}`}</span>;
}

describe('AppProviders', () => {
  it('uses the React version pinned by the mobile app', () => {
    expect(reactVersion).toBe('19.2.3');
  });

  it('composes the mobile Query and unavailable native-session boundaries', () => {
    render(
      <AppProviders>
        <SessionProbe />
      </AppProviders>,
    );

    expect(screen.getByText('unavailable:native-session-contract-pending')).toBeTruthy();
  });
});
