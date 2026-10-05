import { Image } from 'expo-image';
import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import Svg, { Circle, Path } from 'react-native-svg';

import { PrimaryButton } from '@/components/ui/primary-button';
import { useTheme } from '@/hooks/use-theme';

import { OnboardingAllyPreview } from './onboarding-ally-preview';
import type { AllyColorValue, AllyShape } from './onboarding-state';

export type OnboardingRosterAlly = {
  color: AllyColorValue;
  id: string;
  name: string;
  online: boolean;
  preview: string;
  shape: AllyShape;
  time: string;
};

type OnboardingAlliesScreenProps = {
  accentColor?: string;
  allies: readonly OnboardingRosterAlly[];
  onCreateAlly: () => void;
  onOpenAccount?: () => void;
  onOpenAlly: (allyId: string) => void;
  profileInitials?: string;
};

const TOP_ACTION_SIZE = 40;
const ALLY_ROW_SIZE = 50;
const PRESENCE_DOT_SIZE = 10;
const ROSTER_ACCENT = '#FF5800';

export function OnboardingAlliesScreen({
  accentColor = ROSTER_ACCENT,
  allies,
  onCreateAlly,
  onOpenAccount,
  onOpenAlly,
  profileInitials = 'SD',
}: OnboardingAlliesScreenProps) {
  const theme = useTheme();
  const { bottom: bottomInset } = useSafeAreaInsets();
  const [activeTab, setActiveTab] = useState<'my-allies' | 'routines'>('my-allies');

  return (
    <View style={[styles.root, { backgroundColor: theme.appBackground }]}>
      <SafeAreaView edges={['top', 'bottom']} style={styles.safeArea}>
        <View style={styles.content}>
          <View style={styles.topBar}>
            <View style={styles.topBarActions}>
              {onOpenAccount ? (
                <Pressable accessibilityLabel="Account" accessibilityRole="button" onPress={onOpenAccount} style={[styles.profileButton, { backgroundColor: theme.controlSurface }]}>
                  <Text style={[styles.profileInitials, { color: theme.primaryText }]}>{profileInitials}</Text>
                </Pressable>
              ) : (
                <View accessibilityLabel="Account" accessible style={[styles.profileButton, { backgroundColor: theme.controlSurface }]}>
                  <Text style={[styles.profileInitials, { color: theme.primaryText }]}>{profileInitials}</Text>
                </View>
              )}
              <View accessibilityLabel="Chef" accessible>
                <Image
                  accessibilityLabel=""
                  contentFit="contain"
                  source={require('@/assets/allies/icons/chef-hat.svg')}
                  style={styles.actionIcon}
                />
              </View>
            </View>
            <View accessibilityLabel="Search Allies" accessible style={[styles.searchButton, { backgroundColor: theme.controlSurface }]}>
              <SearchIcon color={theme.icon} />
            </View>
          </View>

          <View style={styles.tabs}>
            <Pressable
              accessibilityLabel="My allies"
              accessibilityRole="tab"
              accessibilityState={{ selected: activeTab === 'my-allies' }}
              onPress={() => setActiveTab('my-allies')}
              style={[
                styles.tab,
                { backgroundColor: activeTab === 'my-allies' ? accentColor : theme.neutralButtonSurface },
              ]}>
              <Text
                style={
                  activeTab === 'my-allies'
                    ? styles.selectedTabLabel
                    : [styles.inactiveTabLabel, { color: theme.primaryText }]
                }>
                My allies
              </Text>
            </Pressable>
            <Pressable
              accessibilityLabel="Routines"
              accessibilityRole="tab"
              accessibilityState={{ selected: activeTab === 'routines' }}
              onPress={() => setActiveTab('routines')}
              style={[
                styles.tab,
                { backgroundColor: activeTab === 'routines' ? accentColor : theme.neutralButtonSurface },
              ]}>
              <Text
                style={
                  activeTab === 'routines'
                    ? styles.selectedTabLabel
                    : [styles.inactiveTabLabel, { color: theme.primaryText }]
                }>
                Routines
              </Text>
            </Pressable>
          </View>

          {activeTab === 'my-allies' ? (
            <ScrollView
              contentContainerStyle={styles.listContent}
              showsVerticalScrollIndicator={false}>
              {allies.map((ally) => (
                <Pressable
                  accessibilityLabel={`Open ${ally.name}`}
                  accessibilityRole="button"
                  key={ally.id}
                  onPress={() => onOpenAlly(ally.id)}
                  style={({ pressed }) => [styles.allyRow, pressed && styles.allyRowPressed]}>
                  <View style={styles.allyAvatarWrap}>
                    <OnboardingAllyPreview
                      accessibilityLabel={`${ally.name} Ally`}
                      artworkScale={0.86}
                      color={ally.color}
                      identity={ally.shape}
                      size={ALLY_ROW_SIZE}
                    />
                    {ally.online ? (
                      <View
                        accessibilityLabel="Online"
                        style={[styles.presenceDot, { borderColor: theme.appBackground }]}
                      />
                    ) : null}
                  </View>
                  <View style={styles.allyCopy}>
                    <View style={styles.allyMeta}>
                      <Text numberOfLines={1} style={[styles.allyName, { color: theme.primaryText }]}>{ally.name}</Text>
                      <Text style={styles.allyTime}>{ally.time}</Text>
                    </View>
                    <Text ellipsizeMode="tail" numberOfLines={1} style={[styles.allyPreview, { color: theme.supportingText }]}>
                      {ally.preview}
                    </Text>
                  </View>
                </Pressable>
              ))}
            </ScrollView>
          ) : (
            <View style={styles.emptyView}>
              <Text style={[styles.emptyTitle, { color: theme.primaryText }]}>No routines yet</Text>
              <Text style={[styles.emptySubtitle, { color: theme.supportingText }]}>
                Set up daily routines for your Allies to check in, assist tasks, and keep you on track.
              </Text>
            </View>
          )}

          <View style={[styles.footer, { paddingBottom: Math.max(0, 50 - bottomInset) }]}>
            <View style={styles.createButton}>
              <PrimaryButton
                accentColor={accentColor}
                bottomMargin={0}
                label="Make an ally"
                onPress={onCreateAlly}
              />
            </View>
          </View>
        </View>
      </SafeAreaView>
    </View>
  );
}

function SearchIcon({ color }: { color: string }) {
  return (
    <Svg fill="none" height={24} viewBox="0 0 24 24" width={24}>
      <Circle cx={10.5} cy={10.5} r={6.5} stroke={color} strokeWidth={2.3} />
      <Path d="m15.5 15.5 4.5 4.5" stroke={color} strokeLinecap="round" strokeWidth={2.3} />
    </Svg>
  );
}

const styles = StyleSheet.create({
  actionIcon: {
    height: TOP_ACTION_SIZE,
    width: TOP_ACTION_SIZE,
  },
  allyAvatarWrap: {
    height: ALLY_ROW_SIZE,
    position: 'relative',
    width: ALLY_ROW_SIZE,
  },
  allyCopy: {
    flex: 1,
    minWidth: 0,
  },
  allyMeta: {
    alignItems: 'flex-start',
    flexDirection: 'row',
    justifyContent: 'space-between',
    minWidth: 0,
  },
  allyName: {
    flex: 1,
    fontFamily: 'OpenRundeSemibold',
    fontSize: 18,
    includeFontPadding: true,
    letterSpacing: -1,
    lineHeight: 18,
    marginBottom: 6,
    marginTop: 1.5,
  },
  allyPreview: {
    flex: 1,
    fontFamily: 'OpenRundeMedium',
    fontSize: 14,
    includeFontPadding: true,
    letterSpacing: -0.5,
    lineHeight: 14,
  },
  allyRow: {
    alignItems: 'flex-start',
    flexDirection: 'row',
    gap: 12,
    minHeight: ALLY_ROW_SIZE,
  },
  allyRowPressed: {
    opacity: 0.72,
  },
  allyTime: {
    color: '#A0A0A0',
    flexShrink: 0,
    fontFamily: 'OpenRundeMedium',
    fontSize: 12,
    includeFontPadding: true,
    letterSpacing: -0.5,
    lineHeight: 12,
    marginTop: 2,
    textAlign: 'right',
  },
  content: {
    flex: 1,
  },
  createButton: {
    alignSelf: 'center',
    width: 216,
  },
  emptySubtitle: {
    fontFamily: 'OpenRundeMedium',
    fontSize: 15,
    lineHeight: 22,
    textAlign: 'center',
  },
  emptyTitle: {
    fontFamily: 'OpenRundeSemibold',
    fontSize: 20,
    letterSpacing: -0.5,
    marginBottom: 8,
    textAlign: 'center',
  },
  emptyView: {
    alignItems: 'center',
    flex: 1,
    justifyContent: 'center',
    paddingHorizontal: 32,
  },
  footer: {
    paddingHorizontal: 14,
  },
  inactiveTabLabel: {
    fontFamily: 'OpenRundeSemibold',
    fontSize: 16,
    includeFontPadding: true,
    letterSpacing: -0.7,
    lineHeight: 16,
  },
  listContent: {
    gap: 24,
    paddingBottom: 24,
    paddingHorizontal: 14,
  },
  presenceDot: {
    backgroundColor: '#12C25B',
    borderRadius: PRESENCE_DOT_SIZE / 2,
    borderWidth: 1,
    bottom: 2,
    height: PRESENCE_DOT_SIZE,
    position: 'absolute',
    right: 2,
    width: PRESENCE_DOT_SIZE,
  },
  profileButton: {
    alignItems: 'center',
    borderRadius: 999,
    height: TOP_ACTION_SIZE,
    justifyContent: 'center',
    width: TOP_ACTION_SIZE,
  },
  profileInitials: {
    fontFamily: 'OpenRundeSemibold',
    fontSize: 18,
    includeFontPadding: true,
    letterSpacing: -0.8,
    lineHeight: 18,
  },
  root: {
    flex: 1,
  },
  safeArea: {
    flex: 1,
  },
  searchButton: {
    alignItems: 'center',
    borderRadius: 999,
    height: TOP_ACTION_SIZE,
    justifyContent: 'center',
    width: TOP_ACTION_SIZE,
  },
  selectedTabLabel: {
    color: '#FFFFFF',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 16,
    includeFontPadding: true,
    letterSpacing: -0.7,
    lineHeight: 16,
  },
  tab: {
    alignItems: 'center',
    borderRadius: 100,
    justifyContent: 'center',
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  tabs: {
    flexDirection: 'row',
    gap: 12,
    marginBottom: 18,
    marginTop: 24,
    paddingHorizontal: 14,
  },
  topBar: {
    alignItems: 'center',
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingHorizontal: 14,
    paddingTop: 14,
  },
  topBarActions: {
    alignItems: 'center',
    flexDirection: 'row',
    gap: 12,
  },
});
