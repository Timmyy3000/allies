"use client";

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { isCloudError } from "@allies/cloud-client";
import { SettingsSkeleton } from "@/components/loading-skeletons";
import { BackButton } from "@/components/back-button";
import { currentAccountQueryOptions } from "@/lib/account/account-query";
import { useSession } from "@/lib/session/session-context";
import { AllySettingsDetails } from "./settings-details";
import styles from "../../../account/account.module.css";

export function AllySettingsClient({ allyId }: { allyId: string }) {
  const session = useSession();
  const router = useRouter();
  const started = useRef(false);
  const { restore } = session;
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void restore();
  }, [restore]);
  useEffect(() => {
    if (session.state.status === "signed-out") {
      router.replace(`/sign-in?returnTo=${encodeURIComponent(`/allies/${encodeURIComponent(allyId)}/settings`)}`);
    }
  }, [session.state.status, router, allyId]);

  const account = useQuery({
    ...currentAccountQueryOptions(session.client, session.runCloudOperation),
    enabled: session.state.status === "signed-in",
  });
  const workspaceId = account.data?.workspace.id;
  const ally = useQuery({
    queryKey: ["workspaces", workspaceId, "allies", allyId, "settings"],
    queryFn: ({ signal }) => session.runCloudOperation(
      (operationSignal) => session.client.getAlly(workspaceId!, allyId, operationSignal), { signal },
    ),
    enabled: session.state.status === "signed-in" && Boolean(workspaceId),
  });
  if (session.state.status === "signed-out") return null;
  const error = session.state.status === "unavailable" || account.isError || ally.isError;
  const missing = isCloudError(ally.error) && (ally.error.kind === "forbidden" || ally.error.kind === "not-found");
  if (!error && (session.state.status !== "signed-in" || !ally.data)) return <SettingsSkeleton label="Loading ally settings" />;

  return <main className={styles.page}><div className={styles.shell}>
    <header className={styles.header}>
      <BackButton onClick={() => router.push(`/home/${encodeURIComponent(allyId)}`)} />
      <h1>Ally settings</h1>
    </header>
    {error ? <div>
      <p role="alert">{missing ? "This ally isn't available in your workspace." : "We couldn't load these settings. Try again."}</p>
      {!missing ? <button className={styles.primaryAction} type="button" onClick={() => {
        if (session.state.status === "unavailable") void restore();
        else {
          if (account.isError) void account.refetch();
          if (workspaceId && ally.isError) void ally.refetch();
        }
      }}>Try again</button> : null}
    </div> : ally.data ? <AllySettingsDetails key={ally.data.id} ally={ally.data} label={ally.data.label ?? ""} /> : null}
  </div></main>;
}
