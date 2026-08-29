import { useRouter } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useMemo, useState } from 'react';
import { Image } from 'expo-image';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { PrimaryButton } from '@/components/ui/primary-button';
import { AlliesLogo } from '@/features/onboarding/allies-logo';
import { useNativeSession } from '@/lib/session/session-context';
import { pendingCommandStore } from '@/lib/pending-command-store';
import { useMockApp } from '@/features/mock/mock-app';
import { MockAccountScreen } from '@/features/mock/mock-screens';

import {
  useAvatar,
  useDeleteAvatar,
  useCurrentAccount,
  useUpdateProfile,
  useWorkspace,
} from '@/features/account/account-queries';
import { profileFormSchema } from '@/features/account/profile-schema';
import { useAvatarUpload } from '@/features/account/use-avatar-upload';

export default function AccountScreen() {
  const mock = useMockApp();
  return mock.isMock ? <MockAccountScreen /> : <CloudAccountScreen />;
}

function CloudAccountScreen() {
  const router = useRouter();
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

  if (session.status === 'checking' || session.status === 'refreshing') {
    return <AccountLoading />;
  }

  if (!account) {
    return (
      <AccountStateScreen
        body={session.status === 'offline-with-session'
          ? 'Your session is available, but the account could not be refreshed yet.'
          : 'We could not load your account.'}
        onAction={() => void session.restore()}
        actionLabel="Try again"
      />
    );
  }

  const workspace = workspaceQuery.data ?? account.workspace;
  const avatarUrl = avatarQuery.data?.url ?? account.avatarUrl;

  return (
    <View style={styles.root}>
      <StatusBar style="dark" />
      <SafeAreaView edges={['top', 'bottom']} style={styles.safeArea}>
        <ScrollView contentContainerStyle={styles.scrollContent} keyboardShouldPersistTaps="handled">
          <View style={styles.brandRow}>
            <AlliesLogo height={36} width={42} />
            <Text style={styles.screenTitle}>Your account</Text>
          </View>

          <View style={styles.avatarRow}>
            {avatarUrl ? (
              <Image accessibilityLabel="Profile avatar" contentFit="cover" source={{ uri: avatarUrl }} style={styles.avatar} />
            ) : (
              <View accessibilityLabel="No profile avatar" style={styles.avatarPlaceholder}>
                <Text style={styles.avatarInitial}>{account.displayName.charAt(0).toUpperCase()}</Text>
              </View>
            )}
            <View style={styles.avatarCopy}>
              <Text style={styles.sectionTitle}>Profile</Text>
              <Text style={styles.helperText}>Keep your profile details up to date.</Text>
              <Pressable
                accessibilityRole="button"
                disabled={avatarUpload.isBusy || deleteAvatar.isPending}
                onPress={() => void avatarUpload.pickAndUpload()}
                style={styles.actionLink}>
                <Text style={styles.actionLinkText}>{avatarUpload.isBusy ? 'Updating…' : 'Choose a photo'}</Text>
              </Pressable>
              {avatarUrl ? (
                <Pressable
                  accessibilityRole="button"
                  disabled={avatarUpload.isBusy || deleteAvatar.isPending}
                  onPress={() => deleteAvatar.mutate()}
                  style={styles.actionLink}>
                  <Text style={styles.removeLinkText}>{deleteAvatar.isPending ? 'Removing…' : 'Remove photo'}</Text>
                </Pressable>
              ) : null}
            </View>
          </View>
          {avatarUpload.message ? <Text style={avatarUpload.state === 'error' ? styles.errorText : styles.successText}>{avatarUpload.message}</Text> : null}
          {avatarQuery.isError && avatarQuery.error.kind !== 'not-found' ? (
            <Text style={styles.errorText}>We could not load your current avatar.</Text>
          ) : null}
          {deleteAvatar.isError ? <Text style={styles.errorText}>We could not remove your avatar. Try again.</Text> : null}

          <Text style={styles.label}>Display name</Text>
          <TextInput
            accessibilityLabel="Display name"
            autoCapitalize="words"
            autoCorrect={false}
            onChangeText={(value) => {
              setHasEditedDisplayName(true);
              setDisplayName(value);
            }}
            placeholder="Your name"
            placeholderTextColor="#999999"
            style={styles.input}
            value={inputDisplayName}
          />
          {!profileValidation.success ? <Text style={styles.errorText}>Enter a display name up to 80 characters.</Text> : null}
          {profileMutation.isError ? <Text style={styles.errorText}>We could not save your profile. Try again.</Text> : null}
          <PrimaryButton
            bottomMargin={24}
            disabled={!profileValidation.success || profileMutation.isPending || inputDisplayName === account.displayName}
            label={profileMutation.isPending ? 'Saving…' : 'Save profile'}
            onPress={() => {
              if (profileValidation.success) {
                profileMutation.mutate(profileValidation.data, {
                  onSuccess: () => setHasEditedDisplayName(false),
                });
              }
            }}
          />

          <View style={styles.workspaceCard}>
            <Text style={styles.sectionTitle}>Personal Workspace</Text>
            <Text style={styles.workspaceName}>{workspace.name}</Text>
            <Text style={styles.helperText}>{workspace.role} · {workspace.capabilities.length} capabilities</Text>
            {workspaceQuery.isError ? <Text style={styles.errorText}>Workspace details are temporarily unavailable.</Text> : null}
          </View>

          {session.status === 'offline-with-session' ? (
            <Text style={styles.offlineText}>You’re offline. Changes will need a connection.</Text>
          ) : null}
          <PrimaryButton
            accentColor="#F3F3F3"
            bottomMargin={0}
            label="Sign out"
            onPress={async () => {
              try {
                await pendingCommandStore.clear();
              } catch {
                // Session logout must continue; account binding blocks later command reuse.
              }
              const result = await session.logout();
              if (result.localCleared) router.replace('/sign-in');
            }}
          />
        </ScrollView>
      </SafeAreaView>
    </View>
  );
}

function AccountLoading() {
  return (
    <View style={styles.loadingRoot}>
      <StatusBar style="dark" />
      <AlliesLogo height={70} width={82} />
      <Text style={styles.loadingText}>Checking your account…</Text>
    </View>
  );
}

function AccountStateScreen({ body, actionLabel, onAction }: { body: string; actionLabel: string; onAction: () => void }) {
  return (
    <View style={styles.loadingRoot}>
      <StatusBar style="dark" />
      <Text style={styles.sectionTitle}>Your account</Text>
      <Text style={styles.subtitle}>{body}</Text>
      <PrimaryButton label={actionLabel} onPress={onAction} />
    </View>
  );
}

const styles = StyleSheet.create({
  avatar: {
    backgroundColor: '#F3F3F3',
    borderRadius: 52,
    height: 88,
    width: 88,
  },
  avatarCopy: {
    flex: 1,
    marginLeft: 16,
  },
  avatarInitial: {
    color: '#111111',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 34,
  },
  avatarPlaceholder: {
    alignItems: 'center',
    backgroundColor: '#F3F3F3',
    borderRadius: 52,
    height: 88,
    justifyContent: 'center',
    width: 88,
  },
  avatarRow: {
    alignItems: 'center',
    marginBottom: 32,
  },
  brandRow: {
    alignItems: 'center',
    flexDirection: 'row',
    marginBottom: 36,
  },
  actionLink: {
    alignSelf: 'flex-start',
    marginTop: 8,
  },
  actionLinkText: {
    color: '#FF5800',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 13,
  },
  errorText: {
    color: '#C62828',
    fontFamily: 'OpenRundeMedium',
    fontSize: 13,
    lineHeight: 18,
    marginBottom: 12,
  },
  helperText: {
    color: '#686868',
    fontFamily: 'OpenRundeMedium',
    fontSize: 14,
    lineHeight: 19,
    marginTop: 4,
  },
  input: {
    backgroundColor: '#F3F3F3',
    borderRadius: 24,
    color: '#111111',
    fontFamily: 'OpenRundeMedium',
    fontSize: 17,
    height: 52,
    lineHeight: 22,
    marginBottom: 12,
    paddingHorizontal: 18,
  },
  label: {
    color: '#111111',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 15,
    marginBottom: 8,
  },
  loadingRoot: {
    alignItems: 'center',
    backgroundColor: '#FFFFFF',
    flex: 1,
    justifyContent: 'center',
    padding: 24,
  },
  loadingText: {
    color: '#606060',
    fontFamily: 'OpenRundeMedium',
    fontSize: 16,
    marginTop: 24,
  },
  offlineText: {
    color: '#606060',
    fontFamily: 'OpenRundeMedium',
    fontSize: 14,
    lineHeight: 19,
    marginBottom: 20,
    textAlign: 'center',
  },
  root: {
    backgroundColor: '#FFFFFF',
    flex: 1,
  },
  safeArea: {
    flex: 1,
  },
  screenTitle: {
    color: '#111111',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 28,
    letterSpacing: -1,
    marginLeft: 14,
  },
  scrollContent: {
    paddingBottom: 50,
    paddingHorizontal: 20,
    paddingTop: 24,
  },
  sectionTitle: {
    color: '#111111',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 18,
    lineHeight: 24,
  },
  removeLinkText: {
    color: '#B3261E',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 13,
  },
  successText: {
    color: '#2E7D32',
    fontFamily: 'OpenRundeMedium',
    fontSize: 13,
    lineHeight: 18,
    marginBottom: 12,
  },
  subtitle: {
    color: '#606060',
    fontFamily: 'OpenRundeMedium',
    fontSize: 16,
    lineHeight: 22,
    marginBottom: 24,
    marginTop: 12,
    textAlign: 'center',
  },
  workspaceCard: {
    backgroundColor: '#F3F3F3',
    borderRadius: 24,
    marginBottom: 28,
    padding: 20,
  },
  workspaceName: {
    color: '#111111',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 20,
    marginTop: 16,
  },
});
