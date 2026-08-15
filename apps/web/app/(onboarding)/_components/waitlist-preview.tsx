"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { AllyAvatar } from "@/components/ally-avatar";
import { Artboard } from "@/components/artboard";
import { BackButton } from "@/components/back-button";
import { useOnboardingStore } from "../_store/onboarding-store";
import { WaitlistMappingError } from "../../../lib/waitlist/catalog";
import {
  serializeOnboardingConfiguration,
  useWaitlistFlow,
  waitlistGreetingFingerprint,
} from "../../../lib/waitlist/flow";

function errorMessage(error: { fieldIssues?: Array<{ message?: string }>; code?: string } | null): string | null {
  if (!error) return null;
  return error.fieldIssues?.find((issue) => issue.message)?.message ?? "Something went wrong. Try again.";
}

export function WaitlistPreviewScreen() {
  const name = useOnboardingStore((state) => state.name);
  const shape = useOnboardingStore((state) => state.shape);
  const color = useOnboardingStore((state) => state.color);
  const job = useOnboardingStore((state) => state.job);
  const personalities = useOnboardingStore((state) => state.personalities);
  const personalityNote = useOnboardingStore((state) => state.personalityNote);
  const personalityRaw = useOnboardingStore((state) => state.personalityRaw);
  const goTo = useOnboardingStore((state) => state.goTo);
  const [replyDraft, setReplyDraft] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const savedConfigurationRef = useRef<string | null>(null);
  const failedConfigurationRef = useRef<string | null>(null);
  const requestedGreetingRef = useRef<string | null>(null);
  const {
    snapshot,
    status,
    error,
    pendingAction,
    lastAction,
    saveConfiguration,
    generateGreeting,
    recordReply,
    join,
    retry,
    consentVersion,
  } = useWaitlistFlow();

  const configuration = useMemo(() => {
    try {
      return {
        payload: serializeOnboardingConfiguration({
          name,
          shape,
          color,
          job,
          personalities,
          personalityNote,
          personalityOverride: personalityRaw ?? undefined,
        }),
        mappingError: null,
      };
    } catch (candidate) {
      const mappingError =
        candidate instanceof WaitlistMappingError
          ? candidate
          : new WaitlistMappingError("configuration_invalid", "Check your Ally details and try again.");
      return { payload: null, mappingError };
    }
  }, [color, job, name, personalities, personalityNote, personalityRaw, shape]);

  const localGreetingFingerprint = useMemo(
    () => waitlistGreetingFingerprint(name, job, configuration.payload?.personality ?? null),
    [configuration.payload?.personality, job, name],
  );

  const configurationMatches = Boolean(
    snapshot &&
      configuration.payload &&
      snapshot.configuration.name === configuration.payload.name &&
      snapshot.configuration.appearanceCatalogVersion === configuration.payload.appearance_catalog_version &&
      snapshot.configuration.appearanceKey === configuration.payload.appearance_key &&
      snapshot.configuration.job === configuration.payload.job &&
      (snapshot.configuration.personality ?? undefined) === (configuration.payload.personality ?? undefined),
  );
  const greetingIsCurrent = Boolean(
    snapshot?.greeting &&
      waitlistGreetingFingerprint(
        snapshot.configuration.name ?? "",
        snapshot.configuration.job ?? "",
        snapshot.configuration.personality,
      ) === localGreetingFingerprint,
  );

  useEffect(() => {
    if (status !== "ready" || !snapshot || !configuration.payload || pendingAction) return;
    const configurationKey = JSON.stringify(configuration.payload);
    if (configurationMatches) {
      savedConfigurationRef.current = configurationKey;
      failedConfigurationRef.current = null;
    }
    if (
      !configurationMatches &&
      savedConfigurationRef.current !== configurationKey &&
      failedConfigurationRef.current !== configurationKey
    ) {
      void saveConfiguration(configuration.payload)
        .then(() => {
          savedConfigurationRef.current = configurationKey;
          failedConfigurationRef.current = null;
        })
        .catch(() => {
          failedConfigurationRef.current = configurationKey;
        });
      return;
    }
    if (
      configurationMatches &&
      snapshot.lifecycle === "ready_for_greeting" &&
      (!snapshot.greeting || !greetingIsCurrent) &&
      requestedGreetingRef.current !== localGreetingFingerprint
    ) {
      requestedGreetingRef.current = localGreetingFingerprint;
      void generateGreeting(localGreetingFingerprint).catch(() => undefined);
    }
  }, [
    configuration.payload,
    configurationMatches,
    generateGreeting,
    localGreetingFingerprint,
    pendingAction,
    saveConfiguration,
    snapshot,
    status,
    greetingIsCurrent,
  ]);

  const replyText = replyDraft ?? snapshot?.reply?.text ?? "";
  const isBusy = pendingAction !== null;
  const message = errorMessage(error) ?? configuration.mappingError?.message ?? null;
  const joinedEmail = snapshot?.join?.email ?? null;

  return (
    <Artboard>
      <div
        data-testid="waitlist-preview"
        style={{
          position: "absolute",
          inset: 0,
          overflowY: "auto",
          padding: "82px 20px 28px",
        }}
      >
        <BackButton onClick={() => goTo("personality")} />
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <AllyAvatar shape={shape} color={color ?? "#ff5800"} state="thinking" size={56} />
          <div>
            <p style={{ margin: 0, fontSize: 14, color: "#687078" }}>Your Ally</p>
            <h1 style={{ margin: 0, fontSize: 28, lineHeight: 1.05 }}>{name || "Preview"}</h1>
          </div>
        </div>

        <div
          aria-live="polite"
          data-testid="waitlist-status"
          style={{ marginTop: 22, minHeight: 24, color: message ? "#b8203d" : "#687078" }}
        >
          {message ??
            (pendingAction === "configuration"
              ? "Saving your Ally…"
              : pendingAction === "greeting"
                ? "Writing your Ally’s hello…"
                : status === "loading"
                  ? "Connecting your Ally…"
                  : snapshot?.lifecycle === "greeting_pending"
                    ? "Your Ally is thinking…"
                    : "")}
        </div>

        <section
          aria-label="Ally greeting"
          style={{ marginTop: 12, padding: 18, borderRadius: 18, background: "#f3f3f3", minHeight: 100 }}
        >
          <p style={{ margin: 0, fontSize: 14, color: "#687078" }}>A first hello</p>
          <p data-testid="waitlist-greeting" style={{ margin: "8px 0 0", fontSize: 18, lineHeight: 1.35 }}>
            {greetingIsCurrent ? snapshot?.greeting?.text : "Your Ally will say hello here."}
          </p>
        </section>

        <section aria-label="Reply to your Ally" style={{ marginTop: 18 }}>
          <label htmlFor="waitlist-reply" style={{ display: "block", fontWeight: 600 }}>
            Say something back
          </label>
          <textarea
            id="waitlist-reply"
            value={replyText}
            onChange={(event) => setReplyDraft(event.target.value)}
            maxLength={4000}
            rows={3}
            style={{ display: "block", width: "100%", marginTop: 8, padding: 12, borderRadius: 12, border: "1px solid #d9ddd8", resize: "vertical" }}
          />
          <button
            type="button"
            onClick={() => {
              void recordReply(replyText).then(() => setReplyDraft(null)).catch(() => undefined);
            }}
            disabled={
              isBusy ||
              status !== "ready" ||
              !configurationMatches ||
              !replyText.trim() ||
              !snapshot ||
              Boolean(snapshot.reply)
            }
            style={{ marginTop: 8, border: 0, borderRadius: 999, padding: "10px 16px", color: "#fff", background: "#ff5800" }}
          >
            {pendingAction === "reply" ? "Sending…" : "Save reply"}
          </button>
          {snapshot?.reply ? (
            <p data-testid="waitlist-pending-reply" aria-live="polite" style={{ margin: "10px 0 0", color: "#687078" }}>
              Pending: {snapshot.reply.text}
            </p>
          ) : null}
        </section>

        <section aria-label="Join the waitlist" style={{ marginTop: 18, paddingTop: 18, borderTop: "1px solid #d9ddd8" }}>
          <label htmlFor="waitlist-email" style={{ display: "block", fontWeight: 600 }}>
            Keep this Ally close
          </label>
          <input
            id="waitlist-email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="you@example.com"
            style={{ display: "block", width: "100%", marginTop: 8, padding: 12, borderRadius: 12, border: "1px solid #d9ddd8" }}
          />
          <button
            type="button"
            onClick={() => void join(email.trim()).catch(() => undefined)}
            disabled={
              isBusy ||
              status !== "ready" ||
              !configurationMatches ||
              !email.trim() ||
              !snapshot ||
              !consentVersion ||
              Boolean(joinedEmail)
            }
            style={{ marginTop: 8, border: 0, borderRadius: 999, padding: "10px 16px", color: "#fff", background: "#3446e9" }}
          >
            {pendingAction === "join" ? "Joining…" : "Join the waitlist"}
          </button>
          {!consentVersion && !joinedEmail ? (
            <p style={{ margin: "8px 0 0", color: "#687078" }}>Joining will open soon.</p>
          ) : null}
          {joinedEmail ? (
            <p data-testid="waitlist-join-confirmation" aria-live="polite" style={{ margin: "8px 0 0", color: "#08763e" }}>
              You’re on the list as {joinedEmail}.
            </p>
          ) : null}
        </section>

        {lastAction || status === "error" ? (
          <button
            type="button"
            onClick={() => void retry()}
            disabled={isBusy}
            style={{ marginTop: 18, border: "1px solid #121212", borderRadius: 999, padding: "10px 16px", background: "#fff" }}
          >
            Try again
          </button>
        ) : null}
      </div>
    </Artboard>
  );
}
