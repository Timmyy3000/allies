"use client";

import Link from "next/link";
import { AlliesLoading } from "@/components/allies-loading";
import { BackButton } from "@/components/back-button";
import Image from "next/image";
import { useRouter } from "next/navigation";
import {
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { motion, useReducedMotion } from "motion/react";

import {
  isCloudError,
  type AccountViewModel,
} from "@allies/cloud-client";

import {
  AVATAR_READ_QUERY_KEY,
  CURRENT_ACCOUNT_QUERY_KEY,
  avatarReadQueryOptions,
  currentAccountQueryOptions,
} from "../../lib/account/account-query";
import { uploadAvatar } from "../../lib/account/avatar-upload";
import { profileFormSchema } from "../../lib/account/profile-schema";
import { isStandalonePwa } from "../../lib/pwa/pwa-install";
import { useSession } from "../../lib/session/session-context";

import styles from "./account.module.css";

type AvatarState = "idle" | "uploading" | "deleting" | "success" | "error";

function safeErrorMessage(error: unknown, fallback: string): string {
  if (!isCloudError(error)) return fallback;

  if (error.kind === "unauthorized") return "Your session has ended. Sign in again to continue.";
  if (error.kind === "network" || error.kind === "server" || error.kind === "timeout") {
    return fallback;
  }
  if (error.kind === "security") return "We couldn't complete that securely. Try again.";
  if (error.kind === "forbidden") return "You don't have permission to change this yet.";
  if (error.kind === "validation" || error.code === "avatar_invalid") return "Check the details and try again.";
  return fallback;
}

function initials(displayName: string): string {
  const parts = displayName.trim().split(/\s+/u).filter(Boolean);
  return parts.slice(0, 2).map((part) => part[0]?.toUpperCase() ?? "").join("") || "A";
}

function AccountShell({ children }: { children: React.ReactNode }) {
  return <main className={styles.page}><div className={styles.shell}>{children}</div></main>;
}

function Brand() {
  return <Link className={styles.brand} href="/" aria-label="Allies home"><Image src="/allies-icon.svg" alt="" width={28} height={28} /> allies</Link>;
}

function PendingAccount() {
  return <AlliesLoading label="Restoring your account" />;
}

function UnavailableAccount({ onRetry }: { onRetry: () => void }) {
  return (
    <AccountShell>
      <div className={styles.centerState}>
        <Brand />
        <p className={styles.eyebrow}>A small pause</p>
        <h1>We couldn’t load your account</h1>
        <p className={styles.copy} role="alert">Allies is having trouble reaching your account right now.</p>
        <div className={styles.stateActions}>
          <button type="button" className={styles.primaryAction} onClick={onRetry}>Try again</button>
          <Link className={styles.secondaryAction} href="/">Back to Allies</Link>
        </div>
      </div>
    </AccountShell>
  );
}

export function AccountClient() {
  const reducedMotion = useReducedMotion();
  const session = useSession();
  const router = useRouter();
  const { restore } = session;
  const queryClient = useQueryClient();
  const restoreStarted = useRef(false);
  const uploadController = useRef<AbortController | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const displayNameInput = useRef<HTMLInputElement>(null);
  const [profilePending, setProfilePending] = useState(false);
  const [profileMessage, setProfileMessage] = useState<string | null>(null);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [avatarState, setAvatarState] = useState<AvatarState>("idle");
  const [avatarMessage, setAvatarMessage] = useState<string | null>(null);
  const [avatarError, setAvatarError] = useState<string | null>(null);
  const [logoutPending, setLogoutPending] = useState(false);
  const [logoutMessage, setLogoutMessage] = useState<string | null>(null);

  useEffect(() => {
    if (restoreStarted.current) return;
    restoreStarted.current = true;
    void restore();
  }, [restore]);

  useEffect(() => {
    if (session.state.status === "signed-out" && !logoutPending) router.replace("/");
  }, [logoutPending, router, session.state.status]);

  useEffect(() => () => uploadController.current?.abort(), []);

  const accountQuery = useQuery({
    ...currentAccountQueryOptions(session.client, session.runCloudOperation),
    enabled: session.state.status === "signed-in",
    staleTime: Number.POSITIVE_INFINITY,
  });
  const account = accountQuery.data;
  const avatarQuery = useQuery({
    ...avatarReadQueryOptions(session.client, session.runCloudOperation),
    enabled: session.state.status === "signed-in" && Boolean(account?.avatarUrl),
  });

  if (session.state.status === "unknown" || session.state.status === "restoring") return <PendingAccount />;
  if (session.state.status === "signed-out") return null;
  if (session.state.status === "unavailable") return <UnavailableAccount onRetry={() => void restore()} />;
  if (accountQuery.isError) {
    return <UnavailableAccount onRetry={() => void accountQuery.refetch()} />;
  }
  if (!account || accountQuery.isPending) return <PendingAccount />;

  const avatarUrl = avatarQuery.data?.url ?? account.avatarUrl;
  const avatarBusy = avatarState === "uploading" || avatarState === "deleting";

  const submitProfile = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (profilePending) return;
    setProfileMessage(null);
    setProfileError(null);
    const parsed = profileFormSchema.safeParse({ displayName: displayNameInput.current?.value ?? "" });
    if (!parsed.success) {
      setProfileError(parsed.error.issues[0]?.message ?? "Enter a valid display name.");
      return;
    }

    setProfilePending(true);
    try {
      const profile = await session.runCloudOperation(
        (signal) => session.client.updateProfile(parsed.data.displayName, signal),
        { csrf: true },
      );
      queryClient.setQueryData<AccountViewModel>(CURRENT_ACCOUNT_QUERY_KEY, (current) => current ? {
        ...current,
        displayName: profile.displayName,
        avatarUrl: profile.avatarUrl ?? current.avatarUrl,
      } : current);
      if (displayNameInput.current) displayNameInput.current.value = profile.displayName;
      setProfileMessage("Saved");
    } catch (error) {
      setProfileError(safeErrorMessage(error, "We couldn't save your name. Try again."));
    } finally {
      setProfilePending(false);
    }
  };

  const selectFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] ?? null;
    if (!file) return;
    setSelectedFile(file);
    setAvatarState("idle");
    setAvatarMessage(null);
    setAvatarError(null);
  };

  const uploadSelectedAvatar = async () => {
    if (!selectedFile || avatarBusy) return;
    const controller = new AbortController();
    uploadController.current = controller;
    setAvatarState("uploading");
    setAvatarMessage(null);
    setAvatarError(null);
    try {
      const completed = await uploadAvatar(selectedFile, {
        client: session.client,
        runCloudOperation: session.runCloudOperation,
        signal: controller.signal,
      });
      if (completed.url) queryClient.setQueryData(AVATAR_READ_QUERY_KEY, completed);
      await queryClient.invalidateQueries({ queryKey: CURRENT_ACCOUNT_QUERY_KEY });
      await queryClient.invalidateQueries({ queryKey: AVATAR_READ_QUERY_KEY });
      setSelectedFile(null);
      if (fileInput.current) fileInput.current.value = "";
      setAvatarState("success");
      setAvatarMessage("Avatar saved");
    } catch (error) {
      setAvatarState("error");
      setAvatarError(safeErrorMessage(error, "We couldn't save that avatar. Try again."));
    } finally {
      if (uploadController.current === controller) uploadController.current = null;
    }
  };

  const deleteCurrentAvatar = async () => {
    if (!avatarUrl || avatarBusy) return;
    setAvatarState("deleting");
    setAvatarMessage(null);
    setAvatarError(null);
    try {
      await session.runCloudOperation(
        (signal) => session.client.deleteAvatar(signal),
        { csrf: true },
      );
      queryClient.setQueryData<AccountViewModel>(CURRENT_ACCOUNT_QUERY_KEY, (current) => current ? {
        ...current,
        avatarUrl: null,
      } : current);
      queryClient.removeQueries({ queryKey: AVATAR_READ_QUERY_KEY });
      setAvatarState("success");
      setAvatarMessage("Avatar removed");
    } catch (error) {
      setAvatarState("error");
      setAvatarError(safeErrorMessage(error, "We couldn't remove that avatar. Try again."));
    }
  };

  const logout = async () => {
    if (logoutPending) return;
    setLogoutPending(true);
    setLogoutMessage(null);
    const destination = isStandalonePwa() ? "/app" : "/";
    try {
      const result = await session.logout();
      router.replace(result.serverConfirmed ? destination : `${destination}?signout=unconfirmed`);
    } catch {
      router.replace(`${destination}?signout=unconfirmed`);
    }
  };

  return (
    <AccountShell>
      <header className={styles.header}>
        <BackButton onClick={() => router.push("/home")} />
        <h1>Settings</h1>
      </header>

      <div className={styles.grid}>
        <section className={styles.card} aria-labelledby="avatar-title">
          <div className={styles.sectionHeading}>
            <div>
              <h2 id="avatar-title">Your photo</h2>
              <p className={styles.sectionCopy}>A familiar face in your space.</p>
            </div>
          </div>
          <div className={styles.editor}>
          <div className={styles.avatarRow}>
            <div className={styles.avatarMedium}>
              {avatarUrl ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={avatarUrl} alt="Profile avatar" />
              ) : <span aria-hidden="true">{initials(account.displayName)}</span>}
            </div>
            <div className={styles.avatarCopy}>
              <p className={styles.profileName}>{account.displayName}</p>
              <p>JPEG, PNG, or WebP · up to 5 MB</p>
              {avatarQuery.isError ? (
                <button type="button" className={styles.inlineAction} onClick={() => void avatarQuery.refetch()}>Retry avatar read</button>
              ) : null}
            </div>
          </div>
          <label className={styles.filePicker} htmlFor="avatar-file">
            <span>{avatarUrl ? "Change photo" : "Add a photo"}</span>
            <input
              ref={fileInput}
              id="avatar-file"
              type="file"
              accept="image/jpeg,image/png,image/webp"
              aria-label="Choose a profile avatar"
              onChange={selectFile}
              disabled={avatarBusy}
            />
          </label>
          {selectedFile ? <p className={styles.selectedFile}>Ready to upload: {selectedFile.name}</p> : null}
          {selectedFile ? (
            <button type="button" className={styles.primaryAction} onClick={() => void uploadSelectedAvatar()} disabled={avatarBusy}>
              {avatarState === "error" ? "Retry avatar upload" : avatarBusy ? "Uploading…" : "Upload avatar"}
            </button>
          ) : null}
          {avatarUrl ? (
            <button type="button" className={styles.dangerAction} onClick={() => void deleteCurrentAvatar()} disabled={avatarBusy}>
              {avatarState === "deleting" ? "Removing…" : "Remove avatar"}
            </button>
          ) : null}
          <p className={styles.formStatus} aria-live="polite">{avatarMessage}</p>
          {avatarError ? <p className={styles.formError} role="alert">{avatarError}</p> : null}
          </div>
        </section>

        <section className={styles.card} aria-labelledby="profile-title">
          <div className={styles.sectionHeading}>
            <div>
              <h2 id="profile-title">Your name</h2>
              <p className={styles.sectionCopy}>What your Allies call you.</p>
            </div>
          </div>
          <form className={styles.editor} onSubmit={(event) => void submitProfile(event)}>
            <label className={styles.fieldLabel} htmlFor="display-name">Display name</label>
            <input
              id="display-name"
              name="displayName"
              className={styles.textInput}
              ref={displayNameInput}
              defaultValue={account.displayName}
              onChange={() => {
                setProfileMessage(null);
                setProfileError(null);
              }}
              autoComplete="name"
              maxLength={80}
              required
              aria-invalid={Boolean(profileError)}
              aria-describedby={profileError ? "profile-error" : "profile-status"}
            />
            <button type="submit" className={styles.primaryAction} disabled={profilePending}>
              <motion.span key={profilePending ? "saving" : profileMessage ? "saved" : "save"} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: reducedMotion ? 0 : .12 }}>{profilePending ? "Saving…" : profileMessage ? "Saved ✓" : "Save changes"}</motion.span>
            </button>
            <p id="profile-status" className={styles.formStatus} aria-live="polite">{profileMessage}</p>
            {profileError ? <p id="profile-error" className={styles.formError} role="alert">{profileError}</p> : null}
          </form>
        </section>
      </div>

      <section className={styles.sessionRow} aria-label="Session">
        <button type="button" className={styles.logoutButton} onClick={() => void logout()} disabled={logoutPending}>
          {logoutPending ? "Signing out…" : "Sign out"}
        </button>
      </section>

      {logoutMessage ? <p className={styles.logoutMessage} role="alert">{logoutMessage}</p> : null}
    </AccountShell>
  );
}
