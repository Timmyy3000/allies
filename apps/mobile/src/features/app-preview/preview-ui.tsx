import { SymbolView } from 'expo-symbols';
import { StatusBar } from 'expo-status-bar';
import { useRouter } from 'expo-router';
import type { PropsWithChildren, ReactNode } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { AlliesLogo } from '@/features/onboarding/allies-logo';

import type { PreviewAction, PreviewScreen, PreviewTone } from './screen-map';

export type RootDestination = 'allies' | 'activity' | 'settings';

const tones: Record<PreviewTone, { accent: string; soft: string }> = {
  orange: { accent: '#FF5800', soft: '#FFF0E8' },
  red: { accent: '#FD304F', soft: '#FFE9EE' },
  blue: { accent: '#0D92FD', soft: '#E7F4FF' },
  green: { accent: '#4B9E34', soft: '#ECF8E8' },
  purple: { accent: '#8C5DD6', soft: '#F1EAFE' },
};

export function PreviewPage({
  activeRoot,
  backHref,
  children,
  subtitle,
  title,
}: PropsWithChildren<{ activeRoot?: RootDestination; backHref?: string; subtitle?: string; title: string }>) {
  const router = useRouter();
  return (
    <View style={styles.root}>
      <StatusBar style="dark" />
      <SafeAreaView edges={['top', 'bottom']} style={styles.safeArea}>
        <View style={styles.topRow}>
          {backHref ? (
            <Pressable
              accessibilityLabel="Go back"
              accessibilityRole="button"
              onPress={() => router.replace(backHref as never)}
              style={({ pressed }) => [styles.backButton, pressed && styles.pressed]}>
              <SymbolView
                name={{ ios: 'chevron.left', android: 'chevron_left', web: 'chevron_left' }}
                size={20}
                tintColor="#111111"
                weight="semibold"
              />
            </Pressable>
          ) : <AlliesLogo height={42} width={49} />}
          <View style={styles.previewBadge}><Text style={styles.previewBadgeText}>Preview</Text></View>
        </View>
        <ScrollView contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
          <Text style={styles.pageTitle}>{title}</Text>
          {subtitle ? <Text style={styles.pageSubtitle}>{subtitle}</Text> : null}
          <View style={styles.pageBody}>{children}</View>
        </ScrollView>
        {activeRoot ? <AppBottomNav active={activeRoot} /> : null}
      </SafeAreaView>
    </View>
  );
}

export function AppBottomNav({ active }: { active: RootDestination }) {
  const router = useRouter();
  const items = [
    { id: 'allies' as const, label: 'Allies', href: '/allies', icon: { ios: 'person.2.fill', android: 'group', web: 'group' } },
    { id: 'activity' as const, label: 'Activity', href: '/activity', icon: { ios: 'bolt.fill', android: 'bolt', web: 'bolt' } },
    { id: 'settings' as const, label: 'Settings', href: '/settings', icon: { ios: 'gearshape.fill', android: 'settings', web: 'settings' } },
  ] as const;

  return (
    <View accessibilityRole="tablist" style={styles.bottomNav}>
      {items.map((item) => {
        const selected = item.id === active;
        return (
          <Pressable
            accessibilityRole="tab"
            accessibilityState={{ selected }}
            key={item.id}
            onPress={() => router.replace(item.href as never)}
            style={({ pressed }) => [styles.navItem, pressed && styles.pressed]}>
            <SymbolView name={item.icon} size={21} tintColor={selected ? '#FF5800' : '#8A8A8A'} weight="semibold" />
            <Text style={[styles.navLabel, selected && styles.navLabelActive]}>{item.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

export function PreviewCard({ children, tone }: PropsWithChildren<{ tone?: PreviewTone }>) {
  const palette = tone ? tones[tone] : null;
  return <View style={[styles.card, palette && { backgroundColor: palette.soft }]}>{children}</View>;
}

export function PreviewListRow({
  detail,
  href,
  label,
  tone = 'orange',
}: { detail?: string; href: string; label: string; tone?: PreviewTone }) {
  const router = useRouter();
  const palette = tones[tone];
  return (
    <Pressable
      accessibilityLabel={`Open ${label}`}
      accessibilityRole="button"
      onPress={() => router.push(href as never)}
      style={({ pressed }) => [styles.listRow, pressed && styles.pressed]}>
      <View style={[styles.rowMark, { backgroundColor: palette.accent }]} />
      <View style={styles.rowCopy}>
        <Text style={styles.rowLabel}>{label}</Text>
        {detail ? <Text style={styles.rowDetail}>{detail}</Text> : null}
      </View>
      <Text style={styles.chevron}>›</Text>
    </Pressable>
  );
}

export function PreviewDetailPage({ backHref, screen }: { backHref: string; screen: PreviewScreen | null }) {
  if (!screen) {
    return (
      <PreviewPage backHref={backHref} subtitle="This preview route is not part of the screen map." title="Preview not found">
        <PreviewCard><Text style={styles.bodyText}>Return to the previous screen and choose an available preview.</Text></PreviewCard>
      </PreviewPage>
    );
  }

  const palette = tones[screen.tone];
  return (
    <PreviewPage backHref={backHref} subtitle={screen.summary} title={screen.title}>
      <View style={[styles.status, { backgroundColor: palette.soft }]}>
        <View style={[styles.statusDot, { backgroundColor: palette.accent }]} />
        <Text style={[styles.statusText, { color: palette.accent }]}>{screen.status}</Text>
      </View>
      {screen.progress ? <PreviewProgress {...screen.progress} tone={screen.tone} /> : null}
      <PreviewCard>
        {screen.details.map((detail, index) => (
          <View key={`${detail.label}:${detail.value}`} style={[styles.detail, index > 0 && styles.detailBorder]}>
            <Text style={styles.detailLabel}>{detail.label}</Text>
            <Text style={styles.detailValue}>{detail.value}</Text>
            {detail.note ? <Text style={styles.detailNote}>{detail.note}</Text> : null}
          </View>
        ))}
      </PreviewCard>
      {screen.actions?.length ? <View style={styles.actions}>{screen.actions.map((action) => <PreviewActionButton action={action} key={action.label} />)}</View> : null}
      <Text style={styles.previewNote}>This screen is a visual prototype. Connected behavior will arrive with its accepted product and Cloud contract.</Text>
    </PreviewPage>
  );
}

function PreviewProgress({ label, note, tone, value }: { label: string; note: string; tone: PreviewTone; value: number }) {
  const palette = tones[tone];
  return (
    <View style={styles.progressCard}>
      <View style={styles.progressHeader}><Text style={styles.progressLabel}>{label}</Text><Text style={styles.progressValue}>{Math.round(value * 100)}%</Text></View>
      <View style={styles.progressTrack}><View style={[styles.progressFill, { backgroundColor: palette.accent, width: `${Math.min(1, Math.max(0, value)) * 100}%` }]} /></View>
      <Text style={styles.detailNote}>{note}</Text>
    </View>
  );
}

function PreviewActionButton({ action }: { action: PreviewAction }) {
  const router = useRouter();
  const disabled = action.disabled || !action.href;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled }}
      disabled={disabled}
      onPress={() => action.href && router.push(action.href as never)}
      style={({ pressed }) => [styles.action, disabled && styles.actionDisabled, pressed && styles.pressed]}>
      <Text style={[styles.actionText, disabled && styles.actionTextDisabled]}>{action.label}</Text>
    </Pressable>
  );
}

export function PreviewSectionTitle({ children }: { children: ReactNode }) {
  return <Text style={styles.sectionTitle}>{children}</Text>;
}

const styles = StyleSheet.create({
  action: { alignItems: 'center', backgroundColor: '#111111', borderRadius: 999, minHeight: 50, justifyContent: 'center', paddingHorizontal: 20 },
  actionDisabled: { backgroundColor: '#E5E5E5' },
  actionText: { color: '#FFFFFF', fontFamily: 'OpenRundeSemibold', fontSize: 15 },
  actionTextDisabled: { color: '#8A8A8A' },
  actions: { gap: 10, marginTop: 16 },
  backButton: { alignItems: 'center', backgroundColor: '#F3F3F3', borderRadius: 20, height: 40, justifyContent: 'center', width: 40 },
  bodyText: { color: '#606060', fontFamily: 'OpenRundeMedium', fontSize: 16, lineHeight: 22 },
  bottomNav: { alignItems: 'center', backgroundColor: '#FFFFFF', borderTopColor: '#ECECEC', borderTopWidth: 1, flexDirection: 'row', minHeight: 70, paddingHorizontal: 10, paddingTop: 8 },
  card: { backgroundColor: '#F3F3F3', borderRadius: 24, marginTop: 16, paddingHorizontal: 20, paddingVertical: 8 },
  chevron: { color: '#B2B2B2', fontFamily: 'OpenRundeMedium', fontSize: 28, marginLeft: 12 },
  detail: { paddingVertical: 16 },
  detailBorder: { borderTopColor: '#DCDCDC', borderTopWidth: 1 },
  detailLabel: { color: '#7A7A7A', fontFamily: 'OpenRundeSemibold', fontSize: 12, letterSpacing: 0.2, textTransform: 'uppercase' },
  detailNote: { color: '#727272', fontFamily: 'OpenRundeMedium', fontSize: 13, lineHeight: 18, marginTop: 6 },
  detailValue: { color: '#111111', fontFamily: 'OpenRundeMedium', fontSize: 16, lineHeight: 22, marginTop: 6 },
  listRow: { alignItems: 'center', borderBottomColor: '#E8E8E8', borderBottomWidth: 1, flexDirection: 'row', minHeight: 76, paddingVertical: 12 },
  navItem: { alignItems: 'center', flex: 1, gap: 4, justifyContent: 'center' },
  navLabel: { color: '#8A8A8A', fontFamily: 'OpenRundeSemibold', fontSize: 11 },
  navLabelActive: { color: '#FF5800' },
  pageBody: { marginTop: 26 },
  pageSubtitle: { color: '#606060', fontFamily: 'OpenRundeMedium', fontSize: 16, lineHeight: 22, marginTop: 10, maxWidth: 500 },
  pageTitle: { color: '#111111', fontFamily: 'OpenRundeSemibold', fontSize: 34, letterSpacing: -1.4, lineHeight: 39 },
  pressed: { opacity: 0.72 },
  previewBadge: { backgroundColor: '#FFF0E8', borderRadius: 999, paddingHorizontal: 12, paddingVertical: 7 },
  previewBadgeText: { color: '#FF5800', fontFamily: 'OpenRundeSemibold', fontSize: 12 },
  previewNote: { color: '#8A8A8A', fontFamily: 'OpenRundeMedium', fontSize: 12, lineHeight: 17, marginTop: 18, textAlign: 'center' },
  progressCard: { backgroundColor: '#F8F8F8', borderRadius: 24, marginTop: 16, padding: 20 },
  progressFill: { borderRadius: 4, height: 8 },
  progressHeader: { alignItems: 'center', flexDirection: 'row', justifyContent: 'space-between' },
  progressLabel: { color: '#111111', fontFamily: 'OpenRundeSemibold', fontSize: 15 },
  progressTrack: { backgroundColor: '#E5E5E5', borderRadius: 4, height: 8, marginTop: 14, overflow: 'hidden' },
  progressValue: { color: '#606060', fontFamily: 'OpenRundeSemibold', fontSize: 14 },
  root: { backgroundColor: '#FFFFFF', flex: 1 },
  rowCopy: { flex: 1 },
  rowDetail: { color: '#717171', fontFamily: 'OpenRundeMedium', fontSize: 13, lineHeight: 18, marginTop: 3 },
  rowLabel: { color: '#111111', fontFamily: 'OpenRundeSemibold', fontSize: 16, lineHeight: 20 },
  rowMark: { borderRadius: 4, height: 8, marginRight: 14, width: 8 },
  safeArea: { flex: 1 },
  scrollContent: { paddingBottom: 34, paddingHorizontal: 20 },
  sectionTitle: { color: '#111111', fontFamily: 'OpenRundeSemibold', fontSize: 18, letterSpacing: -0.4, lineHeight: 23, marginBottom: 4, marginTop: 16 },
  status: { alignItems: 'center', alignSelf: 'flex-start', borderRadius: 999, flexDirection: 'row', gap: 8, paddingHorizontal: 13, paddingVertical: 8 },
  statusDot: { borderRadius: 4, height: 8, width: 8 },
  statusText: { fontFamily: 'OpenRundeSemibold', fontSize: 13 },
  topRow: { alignItems: 'center', flexDirection: 'row', justifyContent: 'space-between', minHeight: 74, paddingHorizontal: 20 },
});
