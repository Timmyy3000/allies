import { Pressable, StyleSheet, Text, View } from 'react-native';

import { GlassSurface } from '@/components/ui/glass-surface';
import { useTheme } from '@/hooks/use-theme';

export type HomeNavigationTab = 'allies' | 'routines';
export type HomeNavigationPillLayout = 'center-action' | 'right-action';

export type HomeNavigationPillProps = {
  accentColor?: string;
  activeTab: HomeNavigationTab;
  layout?: HomeNavigationPillLayout;
  onCreateAlly: () => void;
  onTabChange: (tab: HomeNavigationTab) => void;
};

export function HomeNavigationPill({
  accentColor = '#FF5800',
  activeTab,
  layout = 'center-action',
  onCreateAlly,
  onTabChange,
}: HomeNavigationPillProps) {
  const theme = useTheme();

  const renderTab = (tab: HomeNavigationTab, label: string) => {
    const isActive = activeTab === tab;
    return (
      <Pressable
        accessibilityLabel={label}
        accessibilityRole="tab"
        accessibilityState={{ selected: isActive }}
        hitSlop={6}
        key={tab}
        onPress={() => onTabChange(tab)}
        style={({ pressed }) => [
          styles.tab,
          isActive && [styles.activeTab, { backgroundColor: theme.backgroundElement }],
          pressed && styles.tabPressed,
        ]}>
        <Text
          style={[
            styles.tabLabel,
            { color: isActive ? theme.primaryText : theme.textSecondary },
          ]}>
          {label}
        </Text>
      </Pressable>
    );
  };

  const renderAction = () => (
    <Pressable
      accessibilityLabel="Make an ally"
      accessibilityRole="button"
      hitSlop={6}
      key="make-ally"
      onPress={onCreateAlly}
      style={({ pressed }) => [
        styles.actionButton,
        { backgroundColor: accentColor },
        pressed && styles.actionPressed,
      ]}>
      <Text style={styles.actionLabel}>Make an ally</Text>
    </Pressable>
  );

  return (
    <View style={styles.container}>
      <GlassSurface style={[styles.pill, { borderColor: theme.progressTrack }]}>
        <View style={styles.pillContent}>
          {layout === 'center-action' ? (
            <>
              {renderTab('allies', 'Allies')}
              {renderAction()}
              {renderTab('routines', 'Routines')}
            </>
          ) : (
            <>
              {renderTab('allies', 'Allies')}
              {renderTab('routines', 'Routines')}
              {renderAction()}
            </>
          )}
        </View>
      </GlassSurface>
    </View>
  );
}

const styles = StyleSheet.create({
  actionButton: {
    alignItems: 'center',
    borderRadius: 24,
    justifyContent: 'center',
    paddingHorizontal: 16,
    paddingVertical: 10,
  },
  actionLabel: {
    color: '#FFFFFF',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 14,
    letterSpacing: -0.4,
    lineHeight: 18,
  },
  actionPressed: {
    opacity: 0.85,
    transform: [{ scale: 0.97 }],
  },
  activeTab: {
    borderRadius: 22,
  },
  container: {
    alignItems: 'center',
    alignSelf: 'center',
    justifyContent: 'center',
  },
  pill: {
    borderRadius: 32,
    borderWidth: 1,
    elevation: 8,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.1,
    shadowRadius: 12,
  },
  pillContent: {
    alignItems: 'center',
    flexDirection: 'row',
    gap: 6,
    paddingHorizontal: 6,
    paddingVertical: 6,
  },
  tab: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
  tabLabel: {
    fontFamily: 'OpenRundeSemibold',
    fontSize: 14,
    letterSpacing: -0.4,
    lineHeight: 18,
  },
  tabPressed: {
    opacity: 0.75,
  },
});
