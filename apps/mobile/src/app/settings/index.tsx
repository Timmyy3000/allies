import { PreviewCard, PreviewListRow, PreviewPage, PreviewSectionTitle } from '@/features/app-preview/preview-ui';
import { StyleSheet, Text } from 'react-native';

export default function SettingsScreen() {
  return (
    <PreviewPage
      activeRoot="settings"
      subtitle="Your account, preferences, connections, and privacy."
      title="Settings">
      <PreviewCard>
        <Text style={styles.profileName}>Your profile</Text>
        <Text style={styles.profileDetail}>Manage your name and profile picture.</Text>
        <PreviewListRow detail="Connected account" href="/account" label="Open profile" tone="orange" />
      </PreviewCard>

      <PreviewSectionTitle>Account</PreviewSectionTitle>
      <PreviewListRow detail="Google, username, password, and signed-in devices" href="/settings/account-security" label="Account and security" />

      <PreviewSectionTitle>App</PreviewSectionTitle>
      <PreviewListRow detail="Appearance, notifications, and motion" href="/settings/preferences" label="Preferences" />
      <PreviewListRow detail="Google Workspace, Slack, and Notion" href="/settings/connections" label="Connections" tone="blue" />
      <PreviewListRow detail="Your simple seven-day window" href="/settings/usage" label="Usage and billing" tone="purple" />
      <PreviewListRow detail="Data, privacy, and signed-in devices" href="/settings/privacy" label="Privacy and sessions" tone="green" />

      <PreviewSectionTitle>Allies</PreviewSectionTitle>
      <PreviewListRow detail="Identity, responsibilities, routines, access, and deletion" href="/allies/sample/settings" label="Ally settings" tone="red" />

    </PreviewPage>
  );
}

const styles = StyleSheet.create({
  profileDetail: {
    color: '#606060',
    fontFamily: 'OpenRundeMedium',
    fontSize: 14,
    lineHeight: 20,
    marginTop: 4,
  },
  profileName: {
    color: '#111111',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 20,
    lineHeight: 25,
    marginTop: 12,
  },
});
