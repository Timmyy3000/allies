import type { AllyViewModel, RoutineDiscoverySummary } from '@allies/cloud-client';
import { StatusBar } from 'expo-status-bar';
import { useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Svg, { Circle, Path } from 'react-native-svg';

import { BottomSheetModal } from '@/components/ui/bottom-sheet-modal';
import { OnboardingAllyPreview } from '@/features/onboarding/onboarding-ally-preview';
import { OnboardingBackButton } from '@/features/onboarding/onboarding-header';
import { OnboardingLookScreen } from '@/features/onboarding/onboarding-look-screen';
import type { AllyColorValue, AllyShape } from '@/features/onboarding/onboarding-state';
import { useTheme } from '@/hooks/use-theme';

import { getAllyAppearance } from './ally-appearance';
import {
  allyLabelError,
  allySettingsErrorMessage,
  normalizeAllyLabel,
  useAllyRoutine,
  useAllyRoutines,
  useUpdateAllySettings,
} from './profile-queries';

const ROUTINE_PREVIEW = 3;
const LABEL_MAX_LENGTH = 40;
const APPEARANCE_CATALOG_VERSION = 'v1';
const WEEKDAYS = ['', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const ORANGE = '#FF5800';
const DELETE_RED = '#D92D20';

type Sheet = 'label' | 'look' | 'routine' | null;
type Schedule = RoutineDiscoverySummary['schedule'];

export function formatRoutineSchedule(schedule: Schedule): string {
  if (schedule.kind === 'once') {
    const date = new Date(`${schedule.localAt}Z`);
    return date.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' });
  }
  if (schedule.frequency === 'interval') return formatRoutineInterval(schedule.everyMinutes ?? 0);
  const time = schedule.localTime?.slice(0, 5) ?? 'the scheduled time';
  if (schedule.frequency === 'daily') return `${time} every day`;
  if (schedule.frequency === 'weekly') {
    return `${time} every ${(schedule.daysOfWeek ?? []).map((day) => WEEKDAYS[day] ?? '').filter(Boolean).join(', ')}`;
  }
  return `Monthly · day ${schedule.dayOfMonth ?? '—'} at ${time}`;
}

export function formatRoutineInterval(minutes: number): string {
  const [count, unit] = minutes % 1440 === 0 ? [minutes / 1440, 'day'] : minutes % 60 === 0 ? [minutes / 60, 'hour'] : [minutes, 'minute'];
  return count === 1 ? `Every ${unit}` : `Every ${count} ${unit}s`;
}

export function formatNextRun(nextRunAt: string | null, now = new Date()): string | null {
  if (!nextRunAt) return null;
  const next = new Date(nextRunAt);
  if (Number.isNaN(next.getTime())) return null;
  const startOfDay = (date: Date) => new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
  const days = Math.round((startOfDay(next) - startOfDay(now)) / 86_400_000);
  if (days <= 0) return 'Next today';
  if (days === 1) return 'Next tomorrow';
  return `Next in ${days} days`;
}

export function routineSummary(routine: RoutineDiscoverySummary): string {
  if (routine.scheduleState === 'paused') return 'Paused';
  return [formatRoutineSchedule(routine.schedule), formatNextRun(routine.nextRunAt)].filter(Boolean).join(' · ');
}

function formatDay(value: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' });
}

export function AllyProfileScreen({
  ally,
  onBack,
  onDeleteRoutineInChat,
}: {
  ally: AllyViewModel;
  onBack: () => void;
  onDeleteRoutineInChat: (title: string) => void;
}) {
  const theme = useTheme();
  const dark = theme.appBackground === '#000000';
  const listSurface = dark ? '#161616' : '#F7F7F7';
  const appearance = getAllyAppearance(ally.appearance.key);
  const routinesQuery = useAllyRoutines(ally.id);
  const [sheet, setSheet] = useState<Sheet>(null);
  const [routineId, setRoutineId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<'job' | 'personality' | null>(null);
  const [allRoutines, setAllRoutines] = useState(false);
  const label = normalizeAllyLabel(ally.label ?? '');
  const routines = routinesQuery.data?.items ?? [];
  const activeCount = routines.filter((routine) => routine.scheduleState === 'active').length;

  return (
    <View style={[styles.root, { backgroundColor: theme.appBackground }]}>
      <StatusBar style={dark ? 'light' : 'dark'} />
      <SafeAreaView edges={['top', 'bottom']} style={styles.root}>
        <ScrollView contentContainerStyle={styles.scroll}>
          <View style={styles.header}>
            <OnboardingBackButton accessibilityLabel={`Back to ${ally.name}`} onBack={onBack} />
          </View>

          <View style={styles.identity}>
            <Pressable accessibilityLabel="Change look" accessibilityRole="button" onPress={() => setSheet('look')}>
              <OnboardingAllyPreview accessibilityLabel={`${ally.name} Ally`} color={appearance.color} identity={appearance.shape} size={136} />
              <View style={[styles.badge, { backgroundColor: dark ? '#FFFFFF' : '#121212', borderColor: theme.appBackground }]}>
                <PaletteIcon color={dark ? '#121212' : '#FFFFFF'} />
              </View>
            </Pressable>
            <Text style={[styles.name, { color: theme.primaryText }]}>{ally.name}</Text>
            <Pressable accessibilityLabel="Edit label" accessibilityRole="button" onPress={() => setSheet('label')} style={[styles.labelPill, { backgroundColor: theme.controlSurface }]}>
              <Text numberOfLines={1} style={[styles.labelText, { color: label ? theme.primaryText : theme.supportingText }]}>{label || 'Add a label'}</Text>
              <PencilIcon color={theme.supportingText} />
            </Pressable>
          </View>

          <View style={styles.sectionHead}>
            <Text accessibilityRole="header" style={[styles.sectionTitle, { color: theme.primaryText }]}>About</Text>
          </View>
          <View style={[styles.list, { backgroundColor: listSurface }]}>
            {([['job', 'Job', ally.job], ['personality', 'Personality', ally.personality]] as const).map(([key, title, body], index) => (
              <View key={key} style={index > 0 ? [styles.divider, { borderTopColor: dark ? '#262626' : '#EBEBEB' }] : undefined}>
                <Pressable
                  accessibilityRole="button"
                  accessibilityState={{ expanded: expanded === key }}
                  onPress={() => setExpanded(expanded === key ? null : key)}
                  style={styles.row}
                >
                  <Text style={[styles.rowTitle, { color: theme.primaryText }]}>{title}</Text>
                  <ChevronIcon color={theme.supportingText} direction={expanded === key ? 'up' : 'down'} />
                </Pressable>
                {expanded === key ? <Text style={[styles.rowBody, { color: theme.supportingText }]}>{body}</Text> : null}
              </View>
            ))}
          </View>

          {routinesQuery.isPending ? (
            <>
              <View style={styles.sectionHead}>
                <Text accessibilityRole="header" style={[styles.sectionTitle, { color: theme.primaryText }]}>Routines</Text>
              </View>
              <View style={[styles.skeleton, { backgroundColor: listSurface }]} />
            </>
          ) : routinesQuery.isError ? (
            <>
              <View style={styles.sectionHead}>
                <Text accessibilityRole="header" style={[styles.sectionTitle, { color: theme.primaryText }]}>Routines</Text>
              </View>
              <View style={styles.inlineError}>
                <Text style={[styles.inlineErrorText, { color: theme.supportingText }]}>We couldn’t load routines.</Text>
                <Pressable accessibilityRole="button" onPress={() => void routinesQuery.refetch()}>
                  <Text style={styles.link}>Try again</Text>
                </Pressable>
              </View>
            </>
          ) : routines.length > 0 ? (
            <>
              <View style={styles.sectionHead}>
                <Text accessibilityRole="header" style={[styles.sectionTitle, { color: theme.primaryText }]}>Routines</Text>
                <Text style={styles.sectionMeta}>{activeCount} active</Text>
              </View>
              <View style={styles.routines}>
                {(allRoutines ? routines : routines.slice(0, ROUTINE_PREVIEW)).map((routine) => (
                  <Pressable
                    accessibilityRole="button"
                    key={routine.routineId}
                    onPress={() => {
                      setRoutineId(routine.routineId);
                      setSheet('routine');
                    }}
                    style={[styles.routineCard, { backgroundColor: `${appearance.color}14` }]}
                  >
                    <View style={[styles.routineIcon, { backgroundColor: `${appearance.color}24` }]}>
                      <TimerIcon color={appearance.color} size={22} />
                    </View>
                    <View style={styles.routineCopy}>
                      <Text numberOfLines={1} style={[styles.routineTitle, { color: theme.primaryText }]}>{routine.title}</Text>
                      <Text numberOfLines={1} style={[styles.routineSchedule, { color: routine.scheduleState === 'paused' ? theme.supportingText : appearance.color }]}>
                        {routineSummary(routine)}
                      </Text>
                    </View>
                    <ChevronIcon color="#A0A0A0" direction="right" />
                  </Pressable>
                ))}
              </View>
              {!allRoutines && routines.length > ROUTINE_PREVIEW ? (
                <Pressable accessibilityRole="button" onPress={() => setAllRoutines(true)} style={styles.viewAll}>
                  <Text style={styles.link}>View all {routines.length} routines</Text>
                </Pressable>
              ) : null}
            </>
          ) : null}
        </ScrollView>
      </SafeAreaView>

      <LabelSheet ally={ally} visible={sheet === 'label'} onClose={() => setSheet(null)} />
      <LookSheet ally={ally} visible={sheet === 'look'} onClose={() => setSheet(null)} />
      <RoutineSheet
        allyId={ally.id}
        allyName={ally.name}
        accent={appearance.color}
        routineId={routineId}
        visible={sheet === 'routine'}
        onClose={() => setSheet(null)}
        onDeleteInChat={(title) => {
          setSheet(null);
          onDeleteRoutineInChat(title);
        }}
      />
    </View>
  );
}

function SheetHeader({ title, onClose, disabled }: { title: string; onClose: () => void; disabled?: boolean }) {
  const theme = useTheme();
  return (
    <View style={styles.sheetHead}>
      <Text accessibilityRole="header" style={[styles.sheetTitle, { color: theme.primaryText }]}>{title}</Text>
      <CloseButton onClose={onClose} disabled={disabled} />
    </View>
  );
}

function CloseButton({ onClose, disabled }: { onClose: () => void; disabled?: boolean }) {
  const theme = useTheme();
  return (
    <Pressable accessibilityLabel="Close" accessibilityRole="button" disabled={disabled} hitSlop={8} onPress={onClose} style={[styles.sheetClose, { backgroundColor: theme.controlSurface }]}>
      <CloseIcon color={theme.primaryText} />
    </Pressable>
  );
}

function SheetButton({ label, onPress, disabled, background, color }: { label: string; onPress: () => void; disabled?: boolean; background: string; color: string }) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: Boolean(disabled) }}
      disabled={disabled}
      onPress={onPress}
      style={[styles.sheetButton, { backgroundColor: background, opacity: disabled ? 0.45 : 1 }]}
    >
      <Text style={[styles.sheetButtonText, { color }]}>{label}</Text>
    </Pressable>
  );
}

function LabelSheet({ ally, visible, onClose }: { ally: AllyViewModel; visible: boolean; onClose: () => void }) {
  const theme = useTheme();
  const mutation = useUpdateAllySettings(ally.id);
  const [draft, setDraft] = useState<string | null>(null);
  const value = draft ?? ally.label ?? '';
  const normalized = normalizeAllyLabel(value);
  const validation = allyLabelError(value);
  const close = () => {
    setDraft(null);
    mutation.reset();
    onClose();
  };

  return (
    <BottomSheetModal accessibilityLabel="Close label editor" onClose={close} visible={visible}>
      <View style={styles.sheet}>
        <SheetHeader title={`${ally.name}'s label`} onClose={close} disabled={mutation.isPending} />
        <TextInput
          accessibilityLabel="Label"
          autoCorrect={false}
          autoFocus
          editable={!mutation.isPending}
          maxLength={LABEL_MAX_LENGTH}
          onChangeText={(next) => {
            mutation.reset();
            setDraft(next);
          }}
          placeholder="Chief of staff"
          placeholderTextColor={theme.placeholderText}
          style={[styles.input, { borderColor: validation ? DELETE_RED : ORANGE, color: theme.primaryText }]}
          value={value}
        />
        <Text style={styles.counter}>{[...value].length}/{LABEL_MAX_LENGTH}</Text>
        {validation || mutation.error ? (
          <Text accessibilityRole="alert" style={[styles.sheetError, { color: theme.errorText }]}>
            {validation ?? allySettingsErrorMessage(mutation.error, 'label')}
          </Text>
        ) : null}
        <SheetButton
          background={ORANGE}
          color="#FFFFFF"
          disabled={Boolean(validation) || mutation.isPending || draft === null}
          label={mutation.isPending ? 'Saving…' : 'Save'}
          onPress={() => mutation.mutate(
            { label: normalized, showLabel: Boolean(normalized), settingsRevision: ally.settingsRevision ?? 0 },
            { onSuccess: close },
          )}
        />
      </View>
    </BottomSheetModal>
  );
}

function LookSheet({ ally, visible, onClose }: { ally: AllyViewModel; visible: boolean; onClose: () => void }) {
  const mutation = useUpdateAllySettings(ally.id);
  const saved = getAllyAppearance(ally.appearance.key);
  const [draft, setDraft] = useState<{ shape: AllyShape; color: AllyColorValue } | null>(null);
  const look = draft ?? saved;
  const changed = look.shape !== saved.shape || look.color !== saved.color;
  const close = () => {
    setDraft(null);
    mutation.reset();
    onClose();
  };
  const theme = useTheme();

  return (
    <BottomSheetModal accessibilityLabel="Close look editor" onClose={close} visible={visible}>
      <View style={styles.sheet}>
        <SheetHeader title={`How should ${ally.name} look?`} onClose={close} disabled={mutation.isPending} />
        <OnboardingLookScreen
          compact
          allyShape={look.shape}
          hasSwipedAvatar
          selectedColor={look.color}
          onColorChange={(color) => setDraft({ ...look, color })}
          onShapeChange={(shape) => setDraft({ ...look, shape })}
          onSwipe={() => undefined}
        />
        {mutation.error ? (
          <Text accessibilityRole="alert" style={[styles.sheetError, { color: theme.errorText }]}>
            {allySettingsErrorMessage(mutation.error, 'look')}
          </Text>
        ) : null}
        <SheetButton
          background={look.color}
          color={look.color === '#FBE65F' || look.color === '#A3F06F' ? '#121212' : '#FFFFFF'}
          disabled={!changed || mutation.isPending}
          label={mutation.isPending ? 'Saving…' : 'Use this look'}
          onPress={() => mutation.mutate({
            label: normalizeAllyLabel(ally.label ?? ''),
            showLabel: Boolean(ally.showLabel && ally.label),
            settingsRevision: ally.settingsRevision ?? 0,
            appearance: { catalogVersion: APPEARANCE_CATALOG_VERSION, key: `${look.shape}:${look.color.slice(1).toLowerCase()}` },
          }, { onSuccess: close })}
        />
      </View>
    </BottomSheetModal>
  );
}

function RoutineSheet({
  allyId,
  allyName,
  accent,
  routineId,
  visible,
  onClose,
  onDeleteInChat,
}: {
  allyId: string;
  allyName: string;
  accent: string;
  routineId: string | null;
  visible: boolean;
  onClose: () => void;
  onDeleteInChat: (title: string) => void;
}) {
  const theme = useTheme();
  const query = useAllyRoutine(allyId, visible ? routineId : null);
  const routine = query.data;
  const rows: [string, string | null][] = routine ? [
    ['Repeats', formatRoutineSchedule(routine.schedule)],
    ['Next run', routine.scheduleState === 'paused' ? 'Paused' : formatDay(routine.nextRunAt)],
    ['Started', formatDay(routine.createdAt)],
  ] : [];

  return (
    <BottomSheetModal accessibilityLabel="Close routine" onClose={onClose} visible={visible}>
      <View style={styles.sheet}>
        <View style={styles.sheetHead}>
          <View style={[styles.routineSheetIcon, { backgroundColor: `${accent}24` }]}>
            <TimerIcon color={accent} size={28} />
          </View>
          <CloseButton onClose={onClose} />
        </View>
        {query.isPending ? (
          <ActivityIndicator color={theme.supportingText} style={styles.routineLoading} />
        ) : query.isError || !routine ? (
          <View style={styles.inlineError}>
            <Text style={[styles.inlineErrorText, { color: theme.supportingText }]}>We couldn’t load this routine.</Text>
            <Pressable accessibilityRole="button" onPress={() => void query.refetch()}>
              <Text style={styles.link}>Try again</Text>
            </Pressable>
          </View>
        ) : (
          <>
            <Text accessibilityRole="header" style={[styles.routineSheetTitle, { color: theme.primaryText }]}>{routine.title}</Text>
            <View style={styles.facts}>
              {rows.filter(([, value]) => value).map(([label, value]) => (
                <View key={label} style={styles.fact}>
                  <Text style={[styles.factLabel, { color: theme.supportingText }]}>{label}</Text>
                  <Text style={[styles.factValue, { color: theme.primaryText }]}>{value}</Text>
                </View>
              ))}
            </View>
            <View style={[styles.prompt, { backgroundColor: theme.appBackground === '#000000' ? '#1C1C1C' : '#F5F5F5' }]}>
              <Text style={[styles.promptLabel, { color: theme.supportingText }]}>What {allyName} does</Text>
              <Text style={[styles.promptText, { color: theme.primaryText }]}>{routine.executionPrompt}</Text>
            </View>
            <SheetButton
              background={theme.controlSurface}
              color={DELETE_RED}
              label="Delete in chat ↗"
              onPress={() => onDeleteInChat(routine.title)}
            />
          </>
        )}
      </View>
    </BottomSheetModal>
  );
}

export function AllyProfileLoading() {
  const theme = useTheme();
  return (
    <View style={[styles.center, { backgroundColor: theme.appBackground }]}>
      <ActivityIndicator color={theme.supportingText} />
    </View>
  );
}

function PaletteIcon({ color }: { color: string }) {
  return (
    <Svg fill="none" height={18} stroke={color} strokeLinecap="round" strokeWidth={1.4} viewBox="0 0 16 16" width={18}>
      <Path d="M8 2a6 6 0 1 0 0 12c.8 0 1.2-.6 1.2-1.2 0-.8-.6-1-.6-1.8 0-.7.5-1.2 1.2-1.2H11a3 3 0 0 0 3-3C14 4.3 11.3 2 8 2Z" />
      <Circle cx={5} cy={7} fill={color} r={0.6} />
      <Circle cx={7.5} cy={4.8} fill={color} r={0.6} />
      <Circle cx={10.5} cy={5.6} fill={color} r={0.6} />
    </Svg>
  );
}

function PencilIcon({ color }: { color: string }) {
  return (
    <Svg fill="none" height={18} stroke={color} strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.4} viewBox="0 0 16 16" width={18}>
      <Path d="M10.5 2.5 13.5 5.5 5.5 13.5H2.5v-3Z" />
    </Svg>
  );
}

function ChevronIcon({ color, direction }: { color: string; direction: 'up' | 'down' | 'right' }) {
  const d = direction === 'up' ? 'M4 10l4-4 4 4' : direction === 'down' ? 'M4 6l4 4 4-4' : 'M6 3.5 10.5 8 6 12.5';
  return (
    <Svg fill="none" height={16} stroke={color} strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.6} viewBox="0 0 16 16" width={16}>
      <Path d={d} />
    </Svg>
  );
}

function CloseIcon({ color }: { color: string }) {
  return (
    <Svg fill="none" height={18} stroke={color} strokeLinecap="round" strokeWidth={1.8} viewBox="0 0 20 20" width={18}>
      <Path d="M5 5l10 10M15 5 5 15" />
    </Svg>
  );
}

function TimerIcon({ color, size }: { color: string; size: number }) {
  return (
    <Svg fill="none" height={size} stroke={color} strokeLinecap="round" strokeWidth={1.7} viewBox="0 0 20 20" width={size}>
      <Circle cx={10} cy={11} r={6.5} />
      <Path d="M10 8v3.2l2 1.3M8 2.5h4" />
    </Svg>
  );
}

const styles = StyleSheet.create({
  badge: { alignItems: 'center', borderRadius: 22, borderWidth: 3, bottom: 2, height: 44, justifyContent: 'center', position: 'absolute', right: 0, width: 44 },
  center: { alignItems: 'center', flex: 1, justifyContent: 'center' },
  counter: { color: '#A0A0A0', fontFamily: 'OpenRundeMedium', fontSize: 15, marginBottom: 16, marginTop: 10, paddingHorizontal: 2 },
  divider: { borderTopWidth: StyleSheet.hairlineWidth },
  fact: { flexDirection: 'row', gap: 16, justifyContent: 'space-between' },
  factLabel: { fontFamily: 'OpenRundeMedium', fontSize: 17 },
  factValue: { flexShrink: 1, fontFamily: 'OpenRundeMedium', fontSize: 17, textAlign: 'right' },
  facts: { gap: 14, marginBottom: 20 },
  header: { alignItems: 'center', flexDirection: 'row', marginBottom: 8 },
  identity: { alignItems: 'center', gap: 12, marginBottom: 36 },
  inlineError: { alignItems: 'center', flexDirection: 'row', gap: 6, paddingHorizontal: 4 },
  inlineErrorText: { fontFamily: 'OpenRundeMedium', fontSize: 15 },
  input: { borderRadius: 16, borderWidth: 1.5, fontFamily: 'OpenRundeMedium', fontSize: 18, height: 56, paddingHorizontal: 18 },
  labelPill: { alignItems: 'center', borderRadius: 60, flexDirection: 'row', gap: 10, height: 44, maxWidth: '100%', paddingHorizontal: 20 },
  labelText: { flexShrink: 1, fontFamily: 'OpenRundeMedium', fontSize: 17 },
  link: { color: ORANGE, fontFamily: 'OpenRundeSemibold', fontSize: 15 },
  list: { borderRadius: 20, marginBottom: 32, overflow: 'hidden' },
  name: { fontFamily: 'OpenRundeSemibold', fontSize: 32, letterSpacing: -1, marginTop: 8 },
  prompt: { borderRadius: 16, gap: 6, marginBottom: 16, paddingHorizontal: 18, paddingVertical: 16 },
  promptLabel: { fontFamily: 'OpenRundeSemibold', fontSize: 14 },
  promptText: { fontFamily: 'OpenRundeMedium', fontSize: 16, lineHeight: 23 },
  root: { flex: 1 },
  routineCard: { alignItems: 'center', borderRadius: 20, flexDirection: 'row', gap: 14, minHeight: 76, paddingLeft: 16, paddingRight: 18, paddingVertical: 14 },
  routineCopy: { flex: 1, gap: 2 },
  routineIcon: { alignItems: 'center', borderRadius: 22, height: 44, justifyContent: 'center', width: 44 },
  routineLoading: { marginVertical: 32 },
  routineSchedule: { fontFamily: 'OpenRundeMedium', fontSize: 15 },
  routineSheetIcon: { alignItems: 'center', borderRadius: 30, height: 60, justifyContent: 'center', width: 60 },
  routineSheetTitle: { fontFamily: 'OpenRundeSemibold', fontSize: 24, letterSpacing: -0.6, marginBottom: 16 },
  routineTitle: { fontFamily: 'OpenRundeSemibold', fontSize: 18 },
  routines: { gap: 12 },
  row: { alignItems: 'center', flexDirection: 'row', justifyContent: 'space-between', minHeight: 60, paddingHorizontal: 20 },
  rowBody: { fontFamily: 'OpenRundeMedium', fontSize: 16, lineHeight: 23, paddingBottom: 18, paddingHorizontal: 20 },
  rowTitle: { fontFamily: 'OpenRundeMedium', fontSize: 18 },
  scroll: { paddingBottom: 48, paddingHorizontal: 20, paddingTop: 12 },
  sectionHead: { alignItems: 'baseline', flexDirection: 'row', justifyContent: 'space-between', marginBottom: 14, paddingHorizontal: 4 },
  sectionMeta: { color: '#A0A0A0', fontFamily: 'OpenRundeMedium', fontSize: 16 },
  sectionTitle: { fontFamily: 'OpenRundeSemibold', fontSize: 24, letterSpacing: -0.6 },
  sheet: { paddingBottom: 8, paddingHorizontal: 20, paddingTop: 8 },
  sheetButton: { alignItems: 'center', borderRadius: 60, height: 56, justifyContent: 'center', marginTop: 16 },
  sheetButtonText: { fontFamily: 'OpenRundeSemibold', fontSize: 18 },
  sheetClose: { alignItems: 'center', borderRadius: 18, height: 36, justifyContent: 'center', width: 36 },
  sheetError: { fontFamily: 'OpenRundeMedium', fontSize: 14, marginTop: 8 },
  sheetHead: { alignItems: 'center', flexDirection: 'row', gap: 16, justifyContent: 'space-between', marginBottom: 20 },
  sheetTitle: { flex: 1, fontFamily: 'OpenRundeSemibold', fontSize: 24, letterSpacing: -0.6, lineHeight: 30 },
  skeleton: { borderRadius: 20, height: 76 },
  viewAll: { alignSelf: 'flex-start', marginTop: 8, padding: 4 },
});
