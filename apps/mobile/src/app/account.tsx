import { Image } from 'expo-image';
import { StatusBar } from 'expo-status-bar';
import { useRouter } from 'expo-router';
import { useMemo, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { PrimaryButton } from '@/components/ui/primary-button';
import { LiquidGlassBackground } from '@/components/ui/liquid-glass-background';
import { OnboardingBackButton } from '@/features/onboarding/onboarding-header';
import { OnboardingAllyPreview } from '@/features/onboarding/onboarding-ally-preview';
import { useTheme } from '@/hooks/use-theme';
import { useNativeSession } from '@/lib/session/session-context';
import { pendingCommandStore } from '@/lib/pending-command-store';

import {
  useAvatar,
  useCurrentAccount,
  useDeleteAvatar,
  useUpdateProfile,
  useWorkspace,
} from '@/features/account/account-queries';
import { profileFormSchema } from '@/features/account/profile-schema';
import { useAvatarUpload } from '@/features/account/use-avatar-upload';

function initials(name: string): string {
  const parts = name.trim().split(/\s+/u).filter(Boolean);
  return (parts.length > 1 ? `${parts[0][0]}${parts.at(-1)?.[0]}` : parts[0]?.slice(0, 2) ?? '?').toUpperCase();
}

export default function AccountScreen() {
  const router = useRouter();
  const theme = useTheme();
  const session = useNativeSession();
  const accountQuery = useCurrentAccount();
  const account = accountQuery.data ?? session.account;
  const workspaceQuery = useWorkspace(account?.workspace.id ?? '');
  const avatarQuery = useAvatar();
  const avatarUpload = useAvatarUpload();
  const deleteAvatar = useDeleteAvatar();
  const profileMutation = useUpdateProfile();
  const [displayName, setDisplayName] = useState(account?.displayName ?? '');
  const [hasEditedDisplayName, setHasEditedDisplayName] = useState(false);
  const inputDisplayName = hasEditedDisplayName ? displayName : account?.displayName ?? displayName;
  const profileValidation = useMemo(
    () => profileFormSchema.safeParse({ displayName: inputDisplayName }),
    [inputDisplayName],
  );
  const avatarUrl = avatarQuery.data?.url ?? account?.avatarUrl ?? null;

  if (session.status === 'checking' || session.status === 'refreshing') return <AccountLoading />;
  if (!account) {
    return <AccountStateScreen message="We could not load your account." onRetry={() => void session.restore()} />;
  }

  const workspace = workspaceQuery.data ?? account.workspace;

  return (
    <View style={[styles.root, { backgroundColor: theme.appBackground }]}>
      <StatusBar style={theme.appBackground === '#000000' ? 'light' : 'dark'} />
      <SafeAreaView edges={['top', 'bottom']} style={styles.safeArea}>
        <ScrollView contentContainerStyle={styles.scrollContent} keyboardShouldPersistTaps="handled">
          <View style={styles.header}>
            <OnboardingBackButton
              accessibilityLabel="Back to Allies"
              onBack={() => router.replace('/allies' as never)}
            />
            <Text style={[styles.screenTitle, { color: theme.primaryText }]}>Your account</Text>
            <View style={styles.headerPlaceholder} />
          </View>

          <View style={[styles.profileCard, { backgroundColor: theme.controlSurface }]}>
          <View style={styles.avatarRow}>
            {avatarUrl ? (
              <Image accessibilityLabel="Profile avatar" contentFit="cover" source={{ uri: avatarUrl }} style={styles.avatar} />
            ) : (
              <View accessibilityLabel="No profile avatar" style={[styles.avatarPlaceholder, { backgroundColor: theme.controlSurface }]}>
                <Text style={[styles.avatarInitial, { color: theme.primaryText }]}>{initials(account.displayName)}</Text>
              </View>
            )}
            <View style={styles.avatarCopy}>
              <Text style={[styles.sectionTitle, { color: theme.primaryText }]}>Profile</Text>
              <Text style={[styles.helperText, { color: theme.supportingText }]}>Keep your profile details up to date.</Text>
              <Pressable accessibilityRole="button" disabled={avatarUpload.isBusy || deleteAvatar.isPending} onPress={() => void avatarUpload.pickAndUpload()} style={styles.actionLink}>
                <Text style={[styles.actionLinkText, { color: theme.primaryText }]}>{avatarUpload.isBusy ? 'Updating…' : 'Choose a photo'}</Text>
              </Pressable>
              {avatarUrl ? (
                <Pressable accessibilityRole="button" disabled={avatarUpload.isBusy || deleteAvatar.isPending} onPress={() => deleteAvatar.mutate()} style={styles.actionLink}>
                  <Text style={styles.removeLinkText}>{deleteAvatar.isPending ? 'Removing…' : 'Remove photo'}</Text>
                </Pressable>
              ) : null}
            </View>
          </View>
          {avatarUpload.message ? <Text style={avatarUpload.state === 'error' ? styles.errorText : styles.successText}>{avatarUpload.message}</Text> : null}
          {avatarQuery.isError && avatarQuery.error.kind !== 'not-found' ? <Text style={styles.errorText}>We could not load your current avatar.</Text> : null}
          {deleteAvatar.isError ? <Text style={styles.errorText}>We could not remove your avatar. Try again.</Text> : null}

          <Text style={[styles.label, { color: theme.primaryText }]}>Display name</Text>
          <View style={styles.inputSurface}>
            <LiquidGlassBackground borderRadius={24} fallbackColor={theme.controlSurface} />
            <TextInput
              accessibilityLabel="Display name"
              autoCapitalize="words"
              autoCorrect={false}
              onChangeText={(value) => {
                setHasEditedDisplayName(true);
                setDisplayName(value);
              }}
              placeholder="Your name"
              placeholderTextColor={theme.placeholderText}
              style={[styles.input, { color: theme.primaryText }]}
              value={inputDisplayName}
            />
          </View>
          {!profileValidation.success ? <Text style={styles.errorText}>Enter a display name up to 80 characters.</Text> : null}
          {profileMutation.isError ? <Text style={styles.errorText}>We could not save your profile. Try again.</Text> : null}
          <PrimaryButton
            accentColor={theme.primaryText}
            bottomMargin={24}
            disabled={!profileValidation.success || profileMutation.isPending || inputDisplayName === account.displayName}
            label={profileMutation.isPending ? 'Saving…' : 'Save profile'}
            labelColor={theme.appBackground}
            onPress={() => {
              if (profileValidation.success) profileMutation.mutate(profileValidation.data, { onSuccess: () => setHasEditedDisplayName(false) });
            }}
          />
          </View>

          <View style={[styles.workspaceCard, { backgroundColor: theme.controlSurface }]}>
            <Text style={[styles.sectionTitle, { color: theme.primaryText }]}>Personal Workspace</Text>
            <Text style={[styles.workspaceName, { color: theme.primaryText }]}>{workspace.name}</Text>
            <Text style={[styles.helperText, { color: theme.supportingText }]}>{workspace.role} · {workspace.capabilities.length} capabilities</Text>
            {workspaceQuery.isError ? <Text style={styles.errorText}>Workspace details are temporarily unavailable.</Text> : null}
          </View>

          {session.status === 'offline-with-session' ? <Text style={styles.offlineText}>You’re offline. Changes will need a connection.</Text> : null}
          <PrimaryButton
            accentColor={theme.neutralButtonSurface}
            bottomMargin={0}
            label="Sign out"
            labelColor={theme.neutralButtonText}
            onPress={async () => {
              try {
                await pendingCommandStore.clear();
              } catch {
                // Logout still clears the session if a pending command cannot be removed.
              }
              const result = await session.logout();
              if (result.localCleared) router.replace('/');
            }}
          />
        </ScrollView>
      </SafeAreaView>
    </View>
  );
}

function AccountLoading() {
  const theme = useTheme();
  return (
    <View style={[styles.loadingRoot, { backgroundColor: theme.appBackground }]}>
      <StatusBar style={theme.appBackground === '#000000' ? 'light' : 'dark'} />
      <OnboardingAllyPreview accessibilityLabel="Allies loading" color="#FF7A00" identity="boxy" size={72} state="thinking" />
      <Text style={[styles.sectionTitle, { color: theme.primaryText }]}>Checking your account…</Text>
    </View>
  );
}

function AccountStateScreen({ message, onRetry }: { message: string; onRetry: () => void }) {
  const theme = useTheme();
  return (
    <View style={[styles.loadingRoot, { backgroundColor: theme.appBackground }]}>
      <Text style={[styles.sectionTitle, { color: theme.primaryText }]}>Your account</Text>
      <Text style={[styles.subtitle, { color: theme.supportingText }]}>{message}</Text>
      <PrimaryButton label="Try again" onPress={onRetry} />
    </View>
  );
}

const styles = StyleSheet.create({
  actionLink: { alignSelf: 'flex-start', marginTop: 8 },
  actionLinkText: { fontFamily: 'OpenRundeSemibold', fontSize: 13 },
  avatar: { backgroundColor: '#F3F3F3', borderRadius: 52, height: 88, width: 88 },
  avatarCopy: { flex: 1, marginLeft: 16 },
  avatarInitial: { fontFamily: 'OpenRundeSemibold', fontSize: 30 },
  avatarPlaceholder: { alignItems: 'center', borderRadius: 52, height: 88, justifyContent: 'center', width: 88 },
  avatarRow: { alignItems: 'center', marginBottom: 24 },
  errorText: { color: '#B3261E', fontFamily: 'OpenRundeMedium', fontSize: 13, lineHeight: 18, marginBottom: 12 },
  header: { alignItems: 'center', flexDirection: 'row', justifyContent: 'space-between', marginBottom: 24 },
  headerPlaceholder: { height: 48, width: 48 },
  helperText: { fontFamily: 'OpenRundeMedium', fontSize: 14, lineHeight: 19, marginTop: 4 },
  input: { flex: 1, fontFamily: 'OpenRundeMedium', fontSize: 17, lineHeight: 22, paddingHorizontal: 18 },
  inputSurface: { borderRadius: 24, height: 52, marginBottom: 12, overflow: 'hidden' },
  label: { fontFamily: 'OpenRundeSemibold', fontSize: 15, marginBottom: 8 },
  loadingRoot: { alignItems: 'center', flex: 1, justifyContent: 'center', padding: 24 },
  offlineText: { color: '#757575', fontFamily: 'OpenRundeMedium', fontSize: 14, lineHeight: 19, marginBottom: 20, textAlign: 'center' },
  profileCard: { borderRadius: 24, marginBottom: 20, padding: 20 },
  removeLinkText: { color: '#B3261E', fontFamily: 'OpenRundeSemibold', fontSize: 13 },
  root: { flex: 1 },
  safeArea: { flex: 1 },
  screenTitle: { flex: 1, fontFamily: 'OpenRundeSemibold', fontSize: 24, letterSpacing: -1, marginLeft: 14 },
  scrollContent: { paddingBottom: 50, paddingHorizontal: 20, paddingTop: 24 },
  sectionTitle: { fontFamily: 'OpenRundeSemibold', fontSize: 18, lineHeight: 24 },
  subtitle: { fontFamily: 'OpenRundeMedium', fontSize: 16, lineHeight: 22, marginBottom: 24, marginTop: 12, textAlign: 'center' },
  successText: { color: '#2E7D32', fontFamily: 'OpenRundeMedium', fontSize: 13, lineHeight: 18, marginBottom: 12 },
  workspaceCard: { borderRadius: 24, marginBottom: 20, padding: 20 },
  workspaceName: { fontFamily: 'OpenRundeSemibold', fontSize: 20, marginTop: 16 },
});
