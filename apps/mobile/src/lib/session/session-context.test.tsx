// @vitest-environment jsdom

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { NativeSessionProvider, useNativeSession } from './session-context';

function SessionProbe() {
  const session = useNativeSession();
  return <span>{`${session.status}:${session.reason}`}</span>;
}

describe('NativeSessionProvider', () => {
  it('makes the missing native contract explicit', () => {
    render(
      <NativeSessionProvider>
        <SessionProbe />
      </NativeSessionProvider>,
    );

    expect(screen.getByText('unavailable:native-session-contract-pending')).toBeTruthy();
  });
});
