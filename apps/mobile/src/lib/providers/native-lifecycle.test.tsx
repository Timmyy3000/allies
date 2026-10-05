// @vitest-environment jsdom

import { act, render, screen } from '@testing-library/react';
import { focusManager } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { NativeLifecycleBridge, useNativeAppState } from './native-lifecycle';

const appStateHarness = vi.hoisted(() => {
  type State = 'active' | 'background' | 'inactive';
  let state: State = 'active';
  const listeners = new Set<(nextState: State) => void>();
  return {
    AppState: {
      get currentState() {
        return state;
      },
      addEventListener: (_event: 'change', listener: (nextState: State) => void) => {
        listeners.add(listener);
        return { remove: () => listeners.delete(listener) };
      },
    },
    setState(nextState: State) {
      state = nextState;
      for (const listener of listeners) listener(nextState);
    },
    reset() {
      state = 'active';
      listeners.clear();
    },
  };
});

vi.mock('react-native', () => ({ AppState: appStateHarness.AppState }));

function Probe() {
  const state = useNativeAppState();
  return <output data-testid="app-state">{state}</output>;
}

describe('NativeLifecycleBridge', () => {
  it('bridges AppState to the mounted tree and TanStack focus manager', () => {
    const { unmount } = render(
      <NativeLifecycleBridge>
        <Probe />
      </NativeLifecycleBridge>,
    );

    expect(screen.getByTestId('app-state').textContent).toBe('active');
    expect(focusManager.isFocused()).toBe(true);

    act(() => appStateHarness.setState('background'));
    expect(screen.getByTestId('app-state').textContent).toBe('background');
    expect(focusManager.isFocused()).toBe(false);

    act(() => appStateHarness.setState('active'));
    expect(screen.getByTestId('app-state').textContent).toBe('active');
    expect(focusManager.isFocused()).toBe(true);

    unmount();
    act(() => appStateHarness.setState('background'));
    expect(focusManager.isFocused()).toBe(true);
  });

  afterEach(() => {
    appStateHarness.reset();
    focusManager.setEventListener(() => undefined);
    focusManager.setFocused(undefined);
  });
});
