// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createElement, type ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { AllyProfileScreen } from './ally-profile-screen';

const harness = vi.hoisted(() => ({ session: { value: null as unknown } }));

function primitive(tag: 'div' | 'span' | 'button' | 'input') {
  const Primitive = ({ children, accessibilityLabel, accessibilityRole, accessibilityState, onPress, onChangeText, onValueChange, value, disabled }: any) => createElement(
    tag,
    {
      ...(accessibilityLabel ? { 'aria-label': accessibilityLabel } : {}),
      ...(accessibilityRole ? { role: accessibilityRole } : {}),
      ...(accessibilityState?.selected !== undefined ? { 'aria-checked': accessibilityState.selected } : {}),
      ...(onPress ? { onClick: onPress } : {}),
      ...(tag === 'input' ? { value: value ?? '', onChange: (event: any) => onChangeText?.(event.target.value) } : {}),
      ...(onValueChange ? { onClick: () => onValueChange(!value) } : {}),
      ...(disabled ? { disabled: true } : {}),
    },
    children,
  );
  return Primitive;
}

vi.mock('react-native', () => ({
  ActivityIndicator: primitive('span'),
  Pressable: primitive('button'),
  ScrollView: primitive('div'),
  StyleSheet: { create: (styles: unknown) => styles, hairlineWidth: 1 },
  Switch: primitive('button'),
  Text: primitive('span'),
  TextInput: primitive('input'),
  View: primitive('div'),
}));
vi.mock('react-native-safe-area-context', () => ({ SafeAreaView: primitive('div') }));
vi.mock('react-native-svg', () => ({ default: primitive('span'), Circle: primitive('span'), Path: primitive('span') }));
vi.mock('expo-status-bar', () => ({ StatusBar: () => null }));
vi.mock('@/components/ui/bottom-sheet-modal', () => ({
  BottomSheetModal: ({ visible, children }: { visible: boolean; children: ReactNode }) => (visible ? createElement('div', { role: 'dialog' }, children) : null),
}));
vi.mock('@/components/ui/primary-button', () => ({
  PrimaryButton: ({ label, onPress, disabled }: any) => createElement('button', { onClick: onPress, disabled }, label),
}));
vi.mock('@/features/onboarding/onboarding-ally-preview', () => ({ OnboardingAllyPreview: () => null }));
vi.mock('@/features/onboarding/onboarding-look-screen', () => ({
  OnboardingLookScreen: ({ onShapeChange, onColorChange }: any) => createElement('div', null,
    createElement('button', { onClick: () => onShapeChange('rocky') }, 'Choose rocky'),
    createElement('button', { onClick: () => onColorChange('#0D92FD') }, 'Select #0D92FD')),
}));
vi.mock('@/features/onboarding/onboarding-header', () => ({
  OnboardingBackButton: ({ onBack, accessibilityLabel }: any) => createElement('button', { onClick: onBack, 'aria-label': accessibilityLabel }),
}));
vi.mock('@/hooks/use-theme', () => ({
  useTheme: () => ({ appBackground: '#FFFFFF', primaryText: '#121212', supportingText: '#757575', controlSurface: '#F3F3F3', icon: '#121212', placeholderText: '#D9D9D9', errorText: '#B42318' }),
}));
vi.mock('@/lib/session/session-context', () => ({ useNativeSession: () => harness.session.value }));


const workspaceId = '00000000-0000-4000-8000-000000000001';
const allyId = '00000000-0000-4000-8000-000000000002';
const ally = {
  id: allyId,
  bindingId: 'b', operationId: 'o', name: 'Mira', job: 'Plan my week', personality: 'Calm',
  appearance: { catalogVersion: 'v1', key: 'ghosty:ff5800' },
  provisioningState: 'bound', retryable: false,
  label: 'chief of staff', showLabel: true, settingsRevision: 4,
} as never;

const onDeleteRoutineInChat = vi.fn();

function renderProfile(client: Record<string, unknown>) {
  harness.session.value = {
    status: 'signed-in',
    account: { workspace: { id: workspaceId } },
    accountClient: client,
    adapter: { withRefresh: (operation: () => Promise<unknown>) => operation() },
  };
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(createElement(QueryClientProvider, { client: queryClient }, createElement(AllyProfileScreen, { ally, onBack: vi.fn(), onDeleteRoutineInChat })));
}

const routine = (index: number) => ({
  routineId: `r${index}`, responsibleAllyId: 'a', title: `Routine ${index}`,
  schedule: { kind: 'recurring', frequency: 'daily', localTime: '08:00:00', timezone: 'UTC' },
  revision: 1, scheduleGeneration: 1, scheduleState: 'active', nextRunAt: null, createdAt: '', updatedAt: '',
});

afterEach(cleanup);

describe('AllyProfileScreen', () => {
  it('shows three routines, expands the rest, and opens one in a sheet', async () => {
    const getRoutine = vi.fn(async () => ({ ...routine(4), executionPrompt: 'Check the menu.', mainConversationId: 'c' }));
    renderProfile({ listRoutines: vi.fn(async () => ({ items: [1, 2, 3, 4].map(routine), nextCursor: null })), getRoutine });
    expect(await screen.findByText('Routine 3')).toBeTruthy();
    expect(screen.getByText('4 active')).toBeTruthy();
    expect(screen.queryByText('Routine 4')).toBeNull();
    expect(screen.getAllByText('08:00 every day')).toHaveLength(3);
    fireEvent.click(screen.getByText('View all 4 routines'));
    fireEvent.click(screen.getByText('Routine 4'));
    expect(await screen.findByText('Check the menu.')).toBeTruthy();
    expect(screen.getByText('What Mira does')).toBeTruthy();
    fireEvent.click(screen.getByText('Delete in chat ↗'));
    expect(onDeleteRoutineInChat).toHaveBeenCalledWith('Routine 4');
  });

  it('hides routines when there are none', async () => {
    const listRoutines = vi.fn(async () => ({ items: [], nextCursor: null }));
    renderProfile({ listRoutines });
    await waitFor(() => expect(listRoutines).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByText('Routines')).toBeNull());
  });

  it('saves a new look with the current label and revision', async () => {
    const updateAllySettings = vi.fn(async () => ally);
    renderProfile({ listRoutines: vi.fn(async () => ({ items: [], nextCursor: null })), updateAllySettings });
    fireEvent.click(screen.getByLabelText('Change look'));
    expect(screen.getByText('How should Mira look?')).toBeTruthy();
    fireEvent.click(screen.getByText('Choose rocky'));
    fireEvent.click(screen.getByText('Select #0D92FD'));
    fireEvent.click(screen.getByText('Use this look'));
    await waitFor(() => expect(updateAllySettings).toHaveBeenCalledWith(workspaceId, allyId, {
      label: 'chief of staff', showLabel: true, settingsRevision: 4,
      appearance: { catalogVersion: 'v1', key: 'rocky:0d92fd' },
    }));
  });

  it('rejects a one-word label and keeps the sheet open on conflict', async () => {
    const updateAllySettings = vi.fn().mockRejectedValue({ kind: 'conflict', status: 409 });
    renderProfile({ listRoutines: vi.fn(async () => ({ items: [], nextCursor: null })), updateAllySettings });
    fireEvent.click(screen.getByLabelText('Edit label'));
    expect(screen.getByText("Mira's label")).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Label'), { target: { value: 'manager' } });
    expect(screen.getByRole('alert').textContent).toBe('Use two or three words.');
    fireEvent.change(screen.getByLabelText('Label'), { target: { value: 'project manager' } });
    fireEvent.click(screen.getByText('Save'));
    expect((await screen.findByRole('alert')).textContent).toBe('This Ally changed elsewhere. We refreshed it. Try again.');
    expect(screen.getByRole('dialog')).toBeTruthy();
  });
});
