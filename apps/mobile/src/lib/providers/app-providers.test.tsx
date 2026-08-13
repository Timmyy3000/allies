// @vitest-environment jsdom

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { useNativeSession } from '../session/session-context';
import { AppProviders } from './app-providers';

function SessionProbe() {
  const session = useNativeSession();
  return <span>{`${session.status}:${session.reason}`}</span>;
}

describe('AppProviders', () => {
  it('composes the mobile Query and unavailable native-session boundaries', () => {
    process.env.EXPO_PUBLIC_CLOUD_API_URL = 'https://cloud.example.com';

    render(
      <AppProviders>
        <SessionProbe />
      </AppProviders>,
    );

    expect(screen.getByText('unavailable:native-session-contract-pending')).toBeTruthy();
  });
});
