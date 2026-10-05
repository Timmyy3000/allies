"use client";

import { useEffect, useRef, useState } from "react";
import { ConversationComposer, ConversationShell } from "../../home/conversation-frame-primitives";
import chat from "../../home/conversation-frame.module.css";
import styles from "./keyboard-lab.module.css";

type Mode = "current" | "compact" | "pinned";

export function KeyboardLab() {
  const [mode, setMode] = useState<Mode>("current");
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState<string[]>([]);
  const [metrics, setMetrics] = useState("Open the keyboard to measure.");
  const shellRef = useRef<HTMLDivElement>(null);
  const feedRef = useRef<HTMLDivElement>(null);
  const restingViewport = useRef({ width: 0, height: 0 });

  useEffect(() => {
    const shell = shellRef.current;
    const viewport = window.visualViewport;
    if (!shell) return;
    let frame = 0;
    let measureFrame = 0;
    const sync = () => {
      const focused = document.activeElement instanceof HTMLTextAreaElement && shell.contains(document.activeElement);
      const height = viewport?.height ?? window.innerHeight;
      const top = viewport?.offsetTop ?? 0;
      const scale = viewport?.scale ?? 1;
      const unzoomed = Math.abs(scale - 1) < 0.05;
      if (Math.abs(window.innerWidth - restingViewport.current.width) > 80) {
        restingViewport.current = { width: window.innerWidth, height: 0 };
      }
      // Retain the pre-keyboard height when iOS shrinks both viewport APIs together.
      if (!focused && unzoomed) {
        restingViewport.current.height = Math.max(restingViewport.current.height, height);
      }
      const shrink = Math.max(restingViewport.current.height, window.innerHeight) - height;
      const reduced = focused && unzoomed && shrink > 100;
      shell.dataset.keyboard = String(reduced);
      shell.style.setProperty("--lab-height", `${height}px`);
      shell.style.setProperty("--lab-top", `${top}px`);
      shell.style.setProperty("--lab-left", `${viewport?.offsetLeft ?? 0}px`);
      shell.style.setProperty("--lab-width", `${viewport?.width ?? window.innerWidth}px`);
      shell.style.setProperty("--chat-viewport-height", focused ? `${height}px` : "100%");
      shell.style.setProperty("--chat-viewport-offset", focused ? `${top}px` : "0px");
      cancelAnimationFrame(measureFrame);
      measureFrame = requestAnimationFrame(() => {
        const composer = shell.querySelector<HTMLElement>('[data-testid="conversation-composer"]');
        const area = composer?.parentElement;
        const composerBottom = composer?.getBoundingClientRect().bottom ?? 0;
        const shellBottom = shell.getBoundingClientRect().bottom;
        const standalone = matchMedia("(display-mode: standalone)").matches
          || (navigator as Navigator & { standalone?: boolean }).standalone === true;
        setMetrics(`${standalone ? "PWA" : "Browser"} · ${focused ? "focused" : "blurred"} · keyboard ${reduced ? "detected" : "not detected"}\nrest ${Math.round(restingViewport.current.height)} · shrink ${Math.round(shrink)} · inner ${window.innerHeight} · visual ${Math.round(height)}\ntop ${Math.round(top)} · scroll ${Math.round(window.scrollY)} · scale ${scale.toFixed(2)}\nrect bottoms: chat ${Math.round(shellBottom)} / input ${Math.round(composerBottom)}\ninside chat gap ${Math.round(shellBottom - composerBottom)} · padding ${area ? getComputedStyle(area).paddingBottom : "?"}`);
      });
    };
    const schedule = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(sync); };
    sync();
    viewport?.addEventListener("resize", schedule);
    viewport?.addEventListener("scroll", schedule);
    window.addEventListener("resize", schedule);
    window.addEventListener("scroll", schedule);
    shell.addEventListener("focusin", schedule);
    shell.addEventListener("focusout", schedule);
    return () => {
      cancelAnimationFrame(frame);
      cancelAnimationFrame(measureFrame);
      viewport?.removeEventListener("resize", schedule);
      viewport?.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      window.removeEventListener("scroll", schedule);
      shell.removeEventListener("focusin", schedule);
      shell.removeEventListener("focusout", schedule);
    };
  }, [mode, draft]);

  return <main className={styles.host}>
    <ConversationShell accent="#be9bf5" shellRef={shellRef} className={`${chat.frameProduction} ${styles.shell} ${mode === "pinned" ? styles.pinned : ""} ${mode !== "current" ? styles.compact : ""}`}>
      <section className={styles.content}>
        <header className={styles.header}>
          <strong>Keyboard lab <small>v2 · local chat only</small></strong>
          <div className={styles.modes} aria-label="Layout mode">
            {(["current", "compact", "pinned"] as const).map((value, index) => <button key={value} aria-pressed={mode === value} onPointerDown={event => event.preventDefault()} onClick={() => setMode(value)}>{index + 1}. {value === "current" ? "Current" : value === "compact" ? "Inset fix" : "Viewport pin"}</button>)}
          </div>
          <pre className={styles.metrics}>{metrics}</pre>
        </header>
        <div ref={feedRef} className={styles.feed}>
          <p className={styles.label}>Shaka · test conversation</p>
          <p>A tidy desk makes it easier to think and get started. Clear away anything you no longer need, group essentials within easy reach, and give every regular item a home. Keep one small area open for current work, add a little greenery or warmth, and finish with a quick reset each evening. Future-you will appreciate it.</p>
          <p className={styles.hint}>Load this page with the keyboard closed to record its resting height. Tap Reply, switch modes with the keyboard open, then dismiss and reopen it. After rotating, close the keyboard once to recalibrate. Include the measurements above in your screenshot.</p>
          {messages.map((message, index) => <p className={styles.bubble} key={index}>{message}</p>)}
        </div>
      </section>
      <div className={`${chat.frameComposerArea} ${styles.composerArea}`}>
        <ConversationComposer allyName="Shaka" placeholder="Reply Shaka" value={draft} disabled={false} sending={false} onChange={setDraft} onSubmit={() => {
          if (!draft.trim()) return;
          setMessages(previous => [...previous, draft]);
          setDraft("");
          requestAnimationFrame(() => feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight }));
        }} />
      </div>
    </ConversationShell>
  </main>;
}
