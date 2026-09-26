import type { AllyViewModel, RoutineDiscoverySummary } from '@allies/cloud-client';
import { StatusBar } from 'expo-status-bar';
import { useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Switch, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Svg, { Circle, Path } from 'react-native-svg';

import { BottomSheetModal } from '@/components/ui/bottom-sheet-modal';
import { PrimaryButton } from '@/components/ui/primary-button';
import { OnboardingAllyPreview } from '@/features/onboarding/onboarding-ally-preview';
import { OnboardingBackButton } from '@/features/onboarding/onboarding-header';
import { ALLY_COLORS, ALLY_SHAPES, type AllyColorValue, type AllyShape } from '@/features/onboarding/onboarding-state';
import { useTheme } from '@/hooks/use-theme';

import { getAllyAppearance } from './ally-appearance';
import {
  allyLabelError,
  allySettingsErrorMessage,
  normalizeAllyLabel,
  useAllyRoutines,
  useUpdateAllySettings,
} from './profile-queries';

const ROUTINE_PREVIEW = 3;
const APPEARANCE_CATALOG_VERSION = 'v1';
const SHAPE_NAMES: Record<AllyShape, string> = { boxy: 'Boxy', ghosty: 'Ghosty', rocky: 'Rocky', rolly: 'Rolly' };
const WEEKDAYS = ['', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

type Sheet = 'label' | 'look' | null;

export function formatRoutineSchedule(routine: RoutineDiscoverySummary): string {
  if (routine.scheduleState === 'paused') return 'Paused';
  const { schedule } = routine;
  if (schedule.kind === 'once') {
    const date = new Date(`${schedule.localAt}Z`);
    return date.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' });
  }
  const time = schedule.localTime?.slice(0, 5) ?? 'the scheduled time';
  if (schedule.frequency === 'daily') return `${time} every day`;
  if (schedule.frequency === 'weekly') {
    return `${time} every ${(schedule.daysOfWeek ?? []).map((day) => WEEKDAYS[day] ?? '').filter(Boolean).join(', ')}`;
  }
  return `Monthly · day ${schedule.dayOfMonth ?? '—'} at ${time}`;
}

export function AllyProfileScreen({ ally, onBack }: { ally: AllyViewModel; onBack: () => void }) {
  const theme = useTheme();
  const dark = theme.appBackground === '#000000';
  const listSurface = dark ? '#161616' : '#F7F7F7';
  const appearance = getAllyAppearance(ally.appearance.key);
  const routinesQuery = useAllyRoutines(ally.id);
  const [sheet, setSheet] = useState<Sheet>(null);
  const [expanded, setExpanded] = useState<'job' | 'personality' | null>(null);
  const [allRoutines, setAllRoutines] = useState(false);
  const label = normalizeAllyLabel(ally.label ?? '');

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
              <OnboardingAllyPreview accessibilityLabel={`${ally.name} Ally`} color={appearance.color} identity={appearance.shape} size={112} />
              <View style={[styles.badge, { backgroundColor: theme.controlSurface, borderColor: theme.appBackground }]}>
                <PaletteIcon color={theme.icon} />
              </View>
            </Pressable>
            <Text style={[styles.name, { color: theme.primaryText }]}>{ally.name}</Text>
            <Pressable accessibilityLabel="Edit label" accessibilityRole="button" onPress={() => setSheet('label')} style={[styles.labelPill, { backgroundColor: theme.controlSurface }]}>
              <Text style={[styles.labelText, { color: label ? theme.primaryText : theme.supportingText }]}>{label || 'Add a label'}</Text>
              <PencilIcon color={theme.supportingText} />
            </Pressable>
          </View>

          <Text style={[styles.sectionTitle, { color: theme.supportingText }]}>About</Text>
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
                  <ChevronIcon color={theme.supportingText} open={expanded === key} />
                </Pressable>
                {expanded === key ? <Text style={[styles.rowBody, { color: theme.supportingText }]}>{body}</Text> : null}
              </View>
            ))}
          </View>

          {routinesQuery.isPending ? (
            <>
              <Text style={[styles.sectionTitle, { color: theme.supportingText }]}>Routines</Text>
              <View style={[styles.skeleton, { backgroundColor: listSurface }]} />
            </>
          ) : routinesQuery.isError ? (
            <>
              <Text style={[styles.sectionTitle, { color: theme.supportingText }]}>Routines</Text>
              <View style={styles.inlineError}>
                <Text style={[styles.inlineErrorText, { color: theme.supportingText }]}>We couldn&apos;t load routines.</Text>
                <Pressable accessibilityRole="button" onPress={() => void routinesQuery.refetch()}>
                  <Text style={styles.link}>Try again</Text>
                </Pressable>
              </View>
            </>
          ) : routinesQuery.data.items.length > 0 ? (
            <>
              <Text style={[styles.sectionTitle, { color: theme.supportingText }]}>Routines</Text>
              <View style={styles.routines}>
                {(allRoutines ? routinesQuery.data.items : routinesQuery.data.items.slice(0, ROUTINE_PREVIEW)).map((routine) => (
                  <View key={routine.routineId} style={[styles.routineCard, { backgroundColor: `${appearance.color}1A` }]}>
                    <TimerIcon color={appearance.color} />
                    <View style={styles.routineCopy}>
                      <Text numberOfLines={1} style={[styles.routineTitle, { color: theme.primaryText }]}>{routine.title}</Text>
                      <Text numberOfLines={1} style={[styles.routineSchedule, { color: appearance.color }]}>{formatRoutineSchedule(routine)}</Text>
                    </View>
                  </View>
                ))}
              </View>
              {!allRoutines && routinesQuery.data.items.length > ROUTINE_PREVIEW ? (
                <Pressable accessibilityRole="button" onPress={() => setAllRoutines(true)} style={styles.viewAll}>
                  <Text style={styles.link}>View all {routinesQuery.data.items.length} routines</Text>
                </Pressable>
              ) : null}
            </>
          ) : null}
        </ScrollView>
      </SafeAreaView>

      <LabelSheet ally={ally} visible={sheet === 'label'} onClose={() => setSheet(null)} />
      <LookSheet ally={ally} visible={sheet === 'look'} onClose={() => setSheet(null)} />
    </View>
  );
}

function LabelSheet({ ally, visible, onClose }: { ally: AllyViewModel; visible: boolean; onClose: () => void }) {
  const theme = useTheme();
  const mutation = useUpdateAllySettings(ally.id);
  const [draft, setDraft] = useState<{ label: string; showLabel: boolean } | null>(null);
  const current = draft ?? { label: ally.label ?? '', showLabel: Boolean(ally.showLabel && ally.label) };
  const normalized = normalizeAllyLabel(current.label);
  const validation = allyLabelError(current.label);
  const close = () => {
    setDraft(null);
    mutation.reset();
    onClose();
  };

  return (
    <BottomSheetModal accessibilityLabel="Close label editor" onClose={close} visible={visible}>
      <View style={styles.sheet}>
        <Text style={[styles.sheetTitle, { color: theme.primaryText }]}>Edit label</Text>
        <TextInput
          accessibilityLabel="Label"
          autoCorrect={false}
          editable={!mutation.isPending}
          maxLength={80}
          onChangeText={(label) => {
            mutation.reset();
            setDraft({ label, showLabel: current.showLabel && Boolean(normalizeAllyLabel(label)) });
          }}
          placeholder="Chief of staff"
          placeholderTextColor={theme.placeholderText}
          style={[styles.input, { backgroundColor: theme.controlSurface, color: theme.primaryText }]}
          value={current.label}
        />
        <View style={styles.switchRow}>
          <Text style={[styles.rowTitle, { color: theme.primaryText }]}>Show label</Text>
          <Switch
            accessibilityLabel="Show label"
            disabled={mutation.isPending || !normalized}
            onValueChange={(showLabel) => setDraft({ ...current, showLabel })}
            trackColor={{ true: '#FF5800' }}
            value={current.showLabel && Boolean(normalized)}
          />
        </View>
        {validation || mutation.error ? (
          <Text accessibilityRole="alert" style={[styles.sheetError, { color: theme.errorText }]}>
            {validation ?? allySettingsErrorMessage(mutation.error, 'label')}
          </Text>
        ) : null}
        <PrimaryButton
          bottomMargin={0}
          disabled={Boolean(validation) || mutation.isPending || draft === null}
          label={mutation.isPending ? 'Saving…' : 'Save'}
          onPress={() => mutation.mutate(
            { label: normalized, showLabel: current.showLabel && Boolean(normalized), settingsRevision: ally.settingsRevision ?? 0 },
            { onSuccess: close },
          )}
        />
      </View>
    </BottomSheetModal>
  );
}

function LookSheet({ ally, visible, onClose }: { ally: AllyViewModel; visible: boolean; onClose: () => void }) {
  const theme = useTheme();
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

  return (
    <BottomSheetModal accessibilityLabel="Close look editor" onClose={close} visible={visible}>
      <View style={styles.sheet}>
        <Text style={[styles.sheetTitle, { color: theme.primaryText }]}>Change look</Text>
        <View style={styles.lookPreview}>
          <OnboardingAllyPreview accessibilityLabel="Look preview" color={look.color} identity={look.shape} size={104} />
        </View>
        <View style={styles.shapes}>
          {ALLY_SHAPES.map((shape) => (
            <Pressable
              accessibilityLabel={SHAPE_NAMES[shape]}
              accessibilityRole="radio"
              accessibilityState={{ selected: look.shape === shape }}
              key={shape}
              onPress={() => setDraft({ ...look, shape })}
              style={[styles.shape, { backgroundColor: theme.controlSurface, borderColor: look.shape === shape ? theme.primaryText : 'transparent' }]}
            >
              <OnboardingAllyPreview accessibilityLabel="" color={look.color} identity={shape} size={48} />
            </Pressable>
          ))}
        </View>
        <View style={styles.colours}>
          {ALLY_COLORS.map((color) => (
            <Pressable
              accessibilityLabel={color}
              accessibilityRole="radio"
              accessibilityState={{ selected: look.color === color }}
              key={color}
              onPress={() => setDraft({ ...look, color })}
              style={[styles.colourRing, { borderColor: look.color === color ? theme.primaryText : 'transparent' }]}
            >
              <View style={[styles.colour, { backgroundColor: color }]} />
            </Pressable>
          ))}
        </View>
        {mutation.error ? (
          <Text accessibilityRole="alert" style={[styles.sheetError, { color: theme.errorText }]}>
            {allySettingsErrorMessage(mutation.error, 'look')}
          </Text>
        ) : null}
        <PrimaryButton
          bottomMargin={0}
          disabled={!changed || mutation.isPending}
          label={mutation.isPending ? 'Saving…' : 'Save'}
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
    <Svg fill="none" height={16} stroke={color} strokeLinecap="round" strokeWidth={1.4} viewBox="0 0 16 16" width={16}>
      <Path d="M8 2a6 6 0 1 0 0 12c.8 0 1.2-.6 1.2-1.2 0-.8-.6-1-.6-1.8 0-.7.5-1.2 1.2-1.2H11a3 3 0 0 0 3-3C14 4.3 11.3 2 8 2Z" />
      <Circle cx={5} cy={7} fill={color} r={0.6} />
      <Circle cx={7.5} cy={4.8} fill={color} r={0.6} />
      <Circle cx={10.5} cy={5.6} fill={color} r={0.6} />
    </Svg>
  );
}

function PencilIcon({ color }: { color: string }) {
  return (
    <Svg fill="none" height={16} stroke={color} strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.4} viewBox="0 0 16 16" width={16}>
      <Path d="M10.5 2.5 13.5 5.5 5.5 13.5H2.5v-3Z" />
    </Svg>
  );
}

function ChevronIcon({ color, open }: { color: string; open: boolean }) {
  return (
    <Svg fill="none" height={16} stroke={color} strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} viewBox="0 0 16 16" width={16}>
      <Path d={open ? 'M4 10l4-4 4 4' : 'M4 6l4 4 4-4'} />
    </Svg>
  );
}

function TimerIcon({ color }: { color: string }) {
  return (
    <Svg fill="none" height={20} stroke={color} strokeLinecap="round" strokeWidth={1.6} viewBox="0 0 20 20" width={20}>
      <Circle cx={10} cy={11} r={6.5} />
      <Path d="M10 8v3.2l2 1.3M8 2.5h4" />
    </Svg>
  );
}

const styles = StyleSheet.create({
  badge: { alignItems: 'center', borderRadius: 18, borderWidth: 3, bottom: -2, height: 36, justifyContent: 'center', position: 'absolute', right: -2, width: 36 },
  center: { alignItems: 'center', flex: 1, justifyContent: 'center' },
  colour: { borderRadius: 16, height: 32, width: 32 },
  colourRing: { alignItems: 'center', borderRadius: 22, borderWidth: 2, height: 44, justifyContent: 'center', width: 44 },
  colours: { flexDirection: 'row', flexWrap: 'wrap', gap: 4, justifyContent: 'center', marginBottom: 20 },
  divider: { borderTopWidth: StyleSheet.hairlineWidth },
  header: { alignItems: 'center', flexDirection: 'row', marginBottom: 8 },
  identity: { alignItems: 'center', gap: 12, marginBottom: 32 },
  inlineError: { alignItems: 'center', flexDirection: 'row', gap: 6, paddingHorizontal: 4 },
  inlineErrorText: { fontFamily: 'OpenRundeMedium', fontSize: 15 },
  input: { borderRadius: 20, fontFamily: 'OpenRundeMedium', fontSize: 17, height: 52, marginBottom: 12, paddingHorizontal: 18 },
  labelPill: { alignItems: 'center', borderRadius: 60, flexDirection: 'row', gap: 8, height: 40, paddingHorizontal: 16 },
  labelText: { fontFamily: 'OpenRundeMedium', fontSize: 15 },
  link: { color: '#FF5800', fontFamily: 'OpenRundeSemibold', fontSize: 15 },
  list: { borderRadius: 20, marginBottom: 28, overflow: 'hidden' },
  lookPreview: { alignItems: 'center', marginBottom: 20 },
  name: { fontFamily: 'OpenRundeSemibold', fontSize: 26, letterSpacing: -0.8 },
  root: { flex: 1 },
  routineCard: { alignItems: 'center', borderRadius: 20, flexDirection: 'row', gap: 12, minHeight: 60, paddingHorizontal: 16 },
  routineCopy: { flex: 1 },
  routineSchedule: { fontFamily: 'OpenRundeMedium', fontSize: 13, marginTop: 2 },
  routineTitle: { fontFamily: 'OpenRundeSemibold', fontSize: 16 },
  routines: { gap: 8 },
  row: { alignItems: 'center', flexDirection: 'row', justifyContent: 'space-between', minHeight: 54, paddingHorizontal: 18 },
  rowBody: { fontFamily: 'OpenRundeMedium', fontSize: 15, lineHeight: 22, paddingBottom: 16, paddingHorizontal: 18 },
  rowTitle: { fontFamily: 'OpenRundeMedium', fontSize: 16 },
  scroll: { paddingBottom: 48, paddingHorizontal: 20, paddingTop: 12 },
  sectionTitle: { fontFamily: 'OpenRundeSemibold', fontSize: 14, marginBottom: 10, paddingHorizontal: 4 },
  shape: { alignItems: 'center', borderRadius: 20, borderWidth: 2, flex: 1, paddingVertical: 10 },
  shapes: { flexDirection: 'row', gap: 8, marginBottom: 16 },
  sheet: { paddingBottom: 8, paddingHorizontal: 20, paddingTop: 8 },
  sheetError: { fontFamily: 'OpenRundeMedium', fontSize: 14, marginBottom: 12 },
  sheetTitle: { fontFamily: 'OpenRundeSemibold', fontSize: 20, marginBottom: 16, textAlign: 'center' },
  skeleton: { borderRadius: 20, height: 60 },
  switchRow: { alignItems: 'center', flexDirection: 'row', justifyContent: 'space-between', marginBottom: 16, paddingHorizontal: 4 },
  viewAll: { alignSelf: 'flex-start', marginTop: 8, padding: 4 },
});
