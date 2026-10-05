"use client";

import Link from "next/link";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, useSyncExternalStore, type ChangeEvent, type MouseEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { isCloudError, type AccountViewModel } from "@allies/cloud-client";

import { SettingsSkeleton } from "@/components/loading-skeletons";
import { BackButton } from "@/components/back-button";
import {
  AVATAR_READ_QUERY_KEY,
  CURRENT_ACCOUNT_QUERY_KEY,
  avatarReadQueryOptions,
  currentAccountQueryOptions,
} from "../../lib/account/account-query";
import { uploadAvatar } from "../../lib/account/avatar-upload";
import { alliesQueryOptions } from "../../lib/allies/queries";
import { isStandalonePwa } from "../../lib/pwa/pwa-install";
import { logoutDestination } from "../../lib/session/logout-destination";
import { useSession } from "../../lib/session/session-context";
import { playInteractionSound, useInteractionSounds } from "../../lib/interaction-sounds";
import { readThemePreference, subscribeThemePreference, switchTheme, type ThemePreference } from "../../lib/theme/theme";
import sheet from "../home/ally-settings-dialog.module.css";

import { NotificationPreference } from "./notification-preference";
import { AccountConnections } from "./account-connections";
import { Chevron, SettingsSection, SheetLayer } from "./account-parts";
import { AccountSafeInputs } from "./account-safe-inputs";
import { AppearanceSheet, THEME_LABELS } from "./appearance-sheet";
import styles from "./account.module.css";

type AvatarState = "idle" | "uploading" | "deleting" | "error";
const AVATAR_TYPES = "image/jpeg,image/png,image/webp";

function safeErrorMessage(error: unknown, fallback: string): string {
  if (!isCloudError(error)) return fallback;
  if (error.kind === "unauthorized") return "Your session has ended. Sign in again to continue.";
  if (error.kind === "security") return "We couldn't complete that securely. Try again.";
  if (error.kind === "forbidden") return "You don't have permission to change this yet.";
  if (error.kind === "validation" || error.code === "avatar_invalid") return "Use a JPEG, PNG or WebP under 5 MB.";
  return fallback;
}

export function firstName(displayName: string): string {
  return displayName.trim().split(/\s+/u)[0] || "You";
}

function Brand() {
  return <Link className={styles.brand} href="/" aria-label="Allies home"><Image src="/allies-icon.svg" alt="" width={28} height={28} /> allies</Link>;
}

function UnavailableAccount({ onRetry }: { onRetry: () => void }) {
  return (
    <main className={styles.page}>
      <div className={styles.shell}>
        <div className={styles.centerState}>
          <Brand />
          <h1>We couldn’t load your account</h1>
          <p className={styles.copy} role="alert">Allies is having trouble reaching your account right now.</p>
          <div className={styles.stateActions}>
            <button type="button" className={styles.pillPrimary} onClick={onRetry}>Try again</button>
            <Link className={styles.pillAction} href="/">Back to Allies</Link>
          </div>
        </div>
      </div>
    </main>
  );
}

export function AccountClient() {
  const sounds = useInteractionSounds();
  const session = useSession();
  const router = useRouter();
  const { restore } = session;
  const queryClient = useQueryClient();
  const restoreStarted = useRef(false);
  const uploadController = useRef<AbortController | null>(null);
  const appearanceRow = useRef<HTMLButtonElement>(null);
  const storedTheme = useSyncExternalStore(subscribeThemePreference, readThemePreference, () => "system" as const);
  const [pickedTheme, setPickedTheme] = useState<ThemePreference | null>(null);
  const [sheetOpen, setSheetOpen] = useState<"photo" | "appearance" | null>(null);
  const [avatarState, setAvatarState] = useState<AvatarState>("idle");
  const [avatarError, setAvatarError] = useState<string | null>(null);
  const [failedFile, setFailedFile] = useState<File | null>(null);
  const [logoutPending, setLogoutPending] = useState(false);

  useEffect(() => {
    if (restoreStarted.current) return;
    restoreStarted.current = true;
    void restore();
  }, [restore]);

  useEffect(() => {
    if (session.state.status === "signed-out" && !logoutPending) router.replace("/");
  }, [logoutPending, router, session.state.status]);

  useEffect(() => () => uploadController.current?.abort(), []);

  const signedIn = session.state.status === "signed-in";
  const accountQuery = useQuery({
    ...currentAccountQueryOptions(session.client, session.runCloudOperation),
    enabled: signedIn,
    staleTime: Number.POSITIVE_INFINITY,
  });
  const account = accountQuery.data;
  const avatarQuery = useQuery({
    ...avatarReadQueryOptions(session.client, session.runCloudOperation),
    enabled: signedIn && Boolean(account?.avatarUrl),
  });
  const alliesQuery = useQuery({
    ...alliesQueryOptions(session.client, session.runCloudOperation, account?.workspace.id ?? ""),
    enabled: signedIn && Boolean(account),
  });

  if (session.state.status === "unknown" || session.state.status === "restoring") return <SettingsSkeleton label="Loading your account" />;
  if (session.state.status === "signed-out") return null;
  if (session.state.status === "unavailable") return <UnavailableAccount onRetry={() => void restore()} />;
  if (accountQuery.isError) return <UnavailableAccount onRetry={() => void accountQuery.refetch()} />;
  if (!account || accountQuery.isPending) return <SettingsSkeleton label="Loading your account" />;

  const workspaceId = account.workspace.id;
  const allies = alliesQuery.data ?? [];
  const avatarUrl = avatarQuery.data?.url ?? account.avatarUrl;
  const avatarBusy = avatarState === "uploading" || avatarState === "deleting";
  const theme = pickedTheme ?? storedTheme;
  const name = firstName(account.displayName);

  const saveAvatar = async (file: File) => {
    if (avatarBusy) return;
    const controller = new AbortController();
    uploadController.current = controller;
    setAvatarState("uploading");
    setAvatarError(null);
    try {
      const completed = await uploadAvatar(file, {
        client: session.client,
        runCloudOperation: session.runCloudOperation,
        signal: controller.signal,
      });
      if (completed.url) queryClient.setQueryData(AVATAR_READ_QUERY_KEY, completed);
      await queryClient.invalidateQueries({ queryKey: CURRENT_ACCOUNT_QUERY_KEY });
      await queryClient.invalidateQueries({ queryKey: AVATAR_READ_QUERY_KEY });
      setFailedFile(null);
      setAvatarState("idle");
      playInteractionSound("success", { emphasis: "subtle" });
    } catch (error) {
      setFailedFile(file);
      setAvatarState("error");
      setAvatarError(safeErrorMessage(error, "We couldn't save that photo. Try again."));
    } finally {
      if (uploadController.current === controller) uploadController.current = null;
    }
  };

  const pickFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    setSheetOpen(null);
    if (file) void saveAvatar(file);
  };

  const removeAvatar = async () => {
    setSheetOpen(null);
    if (!avatarUrl || avatarBusy) return;
    setAvatarState("deleting");
    setAvatarError(null);
    try {
      await session.runCloudOperation((signal) => session.client.deleteAvatar(signal), { csrf: true });
      queryClient.setQueryData<AccountViewModel>(CURRENT_ACCOUNT_QUERY_KEY, (current) => current && { ...current, avatarUrl: null });
      queryClient.removeQueries({ queryKey: AVATAR_READ_QUERY_KEY });
      setAvatarState("idle");
      playInteractionSound("success", { emphasis: "subtle" });
    } catch (error) {
      setAvatarState("error");
      setAvatarError(safeErrorMessage(error, "We couldn't remove your photo. Try again."));
    }
  };

  const pickTheme = (preference: ThemePreference) => {
    setSheetOpen(null);
    setPickedTheme(preference);
    const rect = appearanceRow.current?.getBoundingClientRect();
    switchTheme(preference, rect ? { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 } : undefined);
  };

  const logout = async (event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    if (logoutPending) return;
    setLogoutPending(true);
    const destination = isStandalonePwa() ? "/app" : "/";
    try {
      const result = await session.logout();
      router.replace(logoutDestination(result, destination));
    } catch {
      router.replace(`${destination}?signout=unconfirmed`);
    }
  };

  return (
    <main className={styles.page}>
      <div className={styles.shell}>
        <header className={styles.header}>
          <BackButton onClick={() => router.push("/home")} />
          <h1>Settings</h1>
          <span aria-hidden="true" />
        </header>

        <section className={styles.profile} aria-label="Profile">
          <button
            type="button"
            className={styles.avatar}
            onClick={() => setSheetOpen("photo")}
            disabled={avatarBusy}
            aria-label={avatarUrl ? "Change profile photo" : "Add a profile photo"}
            aria-busy={avatarBusy}
          >
            {avatarUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={avatarUrl} alt="" />
            ) : <span aria-hidden="true">{(Array.from(name)[0] ?? "").toUpperCase()}</span>}
            <span className={styles.avatarBadge} aria-hidden="true">
              <svg viewBox="0 0 24 24" width="16" height="16"><path d="M4 8h3l2-3h6l2 3h3v11H4z" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" /><circle cx="12" cy="13" r="3.5" fill="none" stroke="currentColor" strokeWidth="2" /></svg>
            </span>
          </button>
          <h2 className={styles.profileName}>{name}</h2>
          <p className={styles.formStatus} aria-live="polite">
            {avatarState === "uploading" ? "Saving your photo…" : avatarState === "deleting" ? "Removing your photo…" : null}
          </p>
          {avatarError ? (
            <p className={styles.inlineError} role="alert">
              {avatarError}{" "}
              {failedFile ? <button type="button" className={styles.textAction} onClick={() => void saveAvatar(failedFile)}>Try again</button> : null}
            </p>
          ) : null}
          {avatarQuery.isError ? (
            <button type="button" className={styles.textAction} onClick={() => void avatarQuery.refetch()}>Reload photo</button>
          ) : null}
        </section>

        <SettingsSection title="Preferences">
          <div className={styles.group}>
            <button ref={appearanceRow} type="button" className={styles.row} onClick={() => setSheetOpen("appearance")}>
              <span className={styles.rowCopy}><strong>Appearance</strong></span>
              <span className={styles.rowValue}>{THEME_LABELS[theme]}</span>
              <Chevron />
            </button>
            {session.push ? <NotificationPreference push={session.push} /> : null}
            <button type="button" className={styles.row} role="switch" aria-label="Interaction sounds" aria-checked={sounds.enabled} onClick={() => sounds.changeEnabled(!sounds.enabled)}>
              <span className={styles.rowCopy}><strong>Interaction sounds</strong><small>Quiet feedback for sends, replies, approvals, and finished routines.</small></span>
              <span className={styles.notificationToggle} data-enabled={sounds.enabled} aria-hidden="true"><span /></span>
            </button>
          </div>
        </SettingsSection>

        <AccountConnections workspaceId={workspaceId} allies={allies} />
        <AccountSafeInputs workspaceId={workspaceId} allies={allies} />

        <SettingsSection title="Privacy and sessions">
          <div className={styles.group}>
            <Link className={styles.row} href="/privacy">
              <span className={styles.rowCopy}><strong>Privacy policy</strong></span>
              <Chevron />
            </Link>
          </div>
          <button type="button" className={styles.greyPill} onClick={(event) => void logout(event)} disabled={logoutPending}>
            {logoutPending ? "Signing out…" : "Sign out"}
          </button>
        </SettingsSection>
      </div>

      {sheetOpen === "photo" ? (
        <SheetLayer onDismiss={() => setSheetOpen(null)}>
          <section className={sheet.subsheet} role="dialog" aria-modal="true" aria-labelledby="photo-title">
            <div className={sheet.subsheetHead}>
              <h3 id="photo-title">Profile photo</h3>
              <button type="button" className={sheet.subsheetClose} aria-label="Close" onClick={() => setSheetOpen(null)}>×</button>
            </div>
            <div className={styles.group}>
              <label className={`${styles.row} ${styles.touchOnly}`}>
                <span className={styles.rowCopy}><strong>Take photo</strong></span>
                <input className={styles.hiddenInput} type="file" accept={AVATAR_TYPES} capture="user" onChange={pickFile} />
              </label>
              <label className={styles.row}>
                <span className={styles.rowCopy}><strong>Choose from library</strong></span>
                <input className={styles.hiddenInput} type="file" accept={AVATAR_TYPES} aria-label="Choose a profile photo" onChange={pickFile} />
              </label>
              {avatarUrl ? (
                <button type="button" className={styles.row} onClick={() => void removeAvatar()}>
                  <span className={`${styles.rowCopy} ${styles.danger}`}><strong>Remove photo</strong></span>
                </button>
              ) : null}
            </div>
          </section>
        </SheetLayer>
      ) : null}

      {sheetOpen === "appearance" ? (
        <AppearanceSheet value={theme} onPick={pickTheme} onClose={() => setSheetOpen(null)} />
      ) : null}
    </main>
  );
}
