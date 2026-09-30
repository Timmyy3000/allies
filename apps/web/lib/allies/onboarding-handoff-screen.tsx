"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { logoutDestination } from "../session/logout-destination";
import { useSession } from "../session/session-context";
import { alliesQueryKey } from "./query-keys";
import { bindOnboardingHandoff, clearOnboardingHandoff, hasOnboardingHandoff } from "./onboarding-handoff";
import { clearOnboardingResume, readOnboardingResume, type OnboardingResumeSnapshot } from "../../app/(onboarding)/_store/onboarding-resume";
import { AuthenticatedAllyFlowProvider } from "./authenticated-onboarding-flow";
import { isStandalonePwa } from "../pwa/pwa-install";
import { OnboardingStateProvider, useOnboardingStore } from "../../app/(onboarding)/_store/onboarding-store";
import { WaitlistPreviewScreen } from "../../app/(onboarding)/_components/waitlist-preview";
import { AuthWelcome } from "../../app/(onboarding)/_components/auth-welcome";

export function OnboardingHandoffScreen() {
  const { client, runCloudOperation, logout } = useSession();
  const router = useRouter();
  const queryClient = useQueryClient();
  const started = useRef(false);
  const [retry, setRetry] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [signingOut, setSigningOut] = useState(false);
  const [welcomeName, setWelcomeName] = useState("");
  const [savedDraft] = useState(readOnboardingResume);
  const [legacy, setLegacy] = useState<{ workspaceId: string; draft: OnboardingResumeSnapshot } | null>(null);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void (async () => {
      try {
        const account = await runCloudOperation((signal) => client.getCurrentAccount(signal));
        setWelcomeName(account.displayName?.trim().split(/\s+/)[0] ?? "");
        const draft = readOnboardingResume();
        if (!hasOnboardingHandoff() && draft) {
          setLegacy({ workspaceId: account.workspace.id, draft });
          return;
        }
        const command = bindOnboardingHandoff(account.userId, account.workspace.id);
        const ally = await runCloudOperation((signal) => client.createAlly(
          account.workspace.id, command.input, command.key, signal,
        ), { csrf: true });
        await queryClient.invalidateQueries({ queryKey: alliesQueryKey(account.workspace.id) });
        clearOnboardingResume();
        clearOnboardingHandoff();
        router.replace(`/home/${encodeURIComponent(ally.id)}`);
      } catch (candidate) {
        setError(candidate instanceof Error ? candidate.message : "We couldn’t finish saving your Ally. Your preview and reply are still saved. Try again.");
      }
    })();
  }, [client, queryClient, retry, router, runCloudOperation]);

  if (legacy) return (
    <OnboardingStateProvider initialStep="preview">
      <AuthenticatedAllyFlowProvider workspaceId={legacy.workspaceId} onCreated={(ally) => {
        clearOnboardingResume();
        router.replace(`/home/${encodeURIComponent(ally.id)}`);
      }}>
        <RestoreLegacyPreview draft={legacy.draft} welcomeName={welcomeName} />
      </AuthenticatedAllyFlowProvider>
    </OnboardingStateProvider>
  );

  if (!error) return <AuthWelcome name={welcomeName} shape={savedDraft?.shape ?? "ghosty"} color={savedDraft?.color ?? "#FF5800"} />;

  return (
    <main className="onboarding-handoff">
      <h1>{error ? "Let’s finish meeting your Ally" : "Opening your Ally…"}</h1>
      <p role={error ? "alert" : "status"}>{error ?? "Saving your first conversation and taking you to the chat."}</p>
      {error && <>
        <button type="button" disabled={signingOut} onClick={() => { started.current = false; setError(null); setRetry((value) => value + 1); }}>Try again</button>
        <button type="button" disabled={signingOut} onClick={() => {
          setSigningOut(true);
          const destination = isStandalonePwa() ? "/app" : "/";
          void logout().then((result) => router.replace(logoutDestination(result, destination)))
            .catch(() => router.replace(`${destination}?signout=unconfirmed`));
        }}>{signingOut ? "Signing out…" : "Sign out to switch accounts"}</button>
        <Link href="/home">Back to chats</Link>
        <p>Your saved Ally and first message will be kept for the original account.</p>
      </>}
    </main>
  );
}

function RestoreLegacyPreview({ draft, welcomeName }: { draft: OnboardingResumeSnapshot; welcomeName: string }) {
  const hydrate = useOnboardingStore((state) => state.hydrate);
  useLayoutEffect(() => hydrate(draft), [draft, hydrate]);
  return <WaitlistPreviewScreen welcomeName={welcomeName} />;
}
