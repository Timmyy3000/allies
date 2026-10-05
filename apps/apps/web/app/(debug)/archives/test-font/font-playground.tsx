"use client";

import { useState, type CSSProperties } from "react";

import {
  ActivityDisclosure,
  AssistantIdentity,
  AssistantMessage,
  ConversationCanvas,
  ConversationComposer,
  ConversationRail,
  ConversationShell,
  DateDivider,
  UserBubble,
  readableAccentForeground,
} from "../../../home/conversation-frame-primitives";

import styles from "./font-playground.module.css";

const activity = [
  { id: "search", text: "Looked through your saved dinner ideas", activityKind: "search", durationMs: 1800 },
  { id: "calendar", text: "Checked the shared calendar for Thursday", activityKind: "calendar", durationMs: 900 },
  { id: "answer", text: "Compared the timings and wrote a plan", tone: "accent" as const, activityKind: "thinking", durationMs: 2400 },
];

const fonts = {
  runde: { label: "Open Runde", family: "var(--font-open-runde), sans-serif" },
  inter: { label: "Inter", family: "var(--font-playground-inter), sans-serif" },
  geist: { label: "Geist", family: "var(--font-playground-geist), sans-serif" },
} as const;

const originalPalette = [
  { label: "Orange", color: "#ff5800" },
  { label: "Pink", color: "#fd304f" },
  { label: "Blue", color: "#0d92fd" },
  { label: "Lavender", color: "#be9bf5" },
  { label: "Indigo", color: "#3446e9" },
  { label: "Green", color: "#a3f06f" },
  { label: "Yellow", color: "#fbe65f" },
] as const;

const blackTextAllyColors = new Set(["#be9bf5", "#a3f06f", "#fbe65f"]);

const lightActivityAccents: Record<string, string> = {
  "#be9bf5": "#7651b5",
  "#a3f06f": "#4a821f",
  "#fbe65f": "#8a7000",
};

function allyAccentForeground(color: string) {
  const normalized = color.toLowerCase();
  if (originalPalette.some((option) => option.color === normalized)) {
    return blackTextAllyColors.has(normalized) ? "#000000" : "#ffffff";
  }
  return readableAccentForeground(color);
}

type FontKey = keyof typeof fonts;
type Theme = "light" | "dark";

export function FontPlayground({ fontVariables }: { fontVariables: string }) {
  const [font, setFont] = useState<FontKey>("runde");
  const [weight, setWeight] = useState("400");
  const [size, setSize] = useState("16");
  const [theme, setTheme] = useState<Theme>("light");
  const [bubbles, setBubbles] = useState(true);
  const [accent, setAccent] = useState("#fd304f");
  const [draft, setDraft] = useState("");
  const onAccent = allyAccentForeground(accent);
  const activityAccent = theme === "light" ? lightActivityAccents[accent.toLowerCase()] ?? accent : accent;
  const previewStyle = {
    "--playground-font": fonts[font].family,
    "--playground-weight": weight,
    "--playground-size": `${size}px`,
    "--playground-on-accent": onAccent,
    "--playground-activity-accent": activityAccent,
  } as CSSProperties;

  const useCodexPreset = () => {
    setFont("geist");
    setWeight("400");
    setSize("14");
    setTheme("light");
  };

  return (
    <main className={`${styles.page} ${fontVariables}`} data-theme={theme}>
      <aside className={styles.controls} aria-label="Chat appearance controls">
        <div className={styles.heading}>
          <p>Allies lab</p>
          <h1>Chat type playground</h1>
          <span>Compare the same conversation across fonts, weights and shell colours.</span>
        </div>

        <button className={styles.preset} type="button" onClick={useCodexPreset}>
          <span>Use Codex today</span>
          <small>Geist · 400 · 14px · Light</small>
        </button>

        <fieldset>
          <legend>Font</legend>
          <div className={styles.segmented}>
            {(Object.entries(fonts) as [FontKey, (typeof fonts)[FontKey]][]).map(([key, option]) => (
              <button key={key} type="button" aria-pressed={font === key} onClick={() => setFont(key)}>{option.label}</button>
            ))}
          </div>
        </fieldset>

        <label className={styles.rangeLabel}>
          <span>Weight <output>{weight}</output></span>
          <input type="range" min="300" max="700" step="100" value={weight} onChange={(event) => setWeight(event.target.value)} />
        </label>

        <label className={styles.rangeLabel}>
          <span>Size <output>{size}px</output></span>
          <input type="range" min="12" max="18" step="1" value={size} onChange={(event) => setSize(event.target.value)} />
        </label>

        <fieldset>
          <legend>Theme</legend>
          <div className={styles.segmented}>
            <button type="button" aria-pressed={theme === "light"} onClick={() => setTheme("light")}>Light</button>
            <button type="button" aria-pressed={theme === "dark"} onClick={() => setTheme("dark")}>Dark</button>
          </div>
        </fieldset>

        <label className={styles.colorControl}>
          <span>Ally shell colour</span>
          <span className={styles.colorInput}>
            <input type="color" value={accent} onChange={(event) => setAccent(event.target.value)} />
            <code>{accent.toUpperCase()}</code>
          </span>
          <small>Palette rule, with contrast calculation for custom colours: <b style={{ color: onAccent }}>{onAccent}</b></small>
        </label>

        <fieldset className={styles.palette}>
          <legend>Original palette</legend>
          <div className={styles.swatches}>
            {originalPalette.map((option) => (
              <button
                key={option.color}
                type="button"
                aria-label={`Original ${option.label}, ${option.color}`}
                aria-pressed={accent === option.color}
                onClick={() => setAccent(option.color)}
                style={{ background: option.color }}
                title={`${option.label} · ${option.color}`}
              >
                {accent === option.color ? "✓" : ""}
              </button>
            ))}
          </div>
          <small>Current production Ally colour choices.</small>
        </fieldset>

        <label className={styles.toggle}>
          <span>Chat bubbles</span>
          <input type="checkbox" checked={bubbles} onChange={(event) => setBubbles(event.target.checked)} />
        </label>
      </aside>

      <section className={styles.stage} aria-label="Simulated conversation preview">
        <div className={styles.device} style={previewStyle} data-bubbles={bubbles}>
          <ConversationShell accent={accent} className={styles.chatShell}>
            <ConversationCanvas>
              <ConversationRail>
                <DateDivider>Thursday</DateDivider>
                <AssistantIdentity avatar={<span className={styles.avatar} style={{ background: accent }}>S</span>} name="Sally" />
                <AssistantMessage>
                  <p>Morning! I kept the plan realistic: one shop, a relaxed prep window, and enough time to eat before the film.</p>
                </AssistantMessage>
                <UserBubble className={bubbles ? styles.accentBubble : styles.bubbleless}>Can you plan a cosy dinner for Thursday? Four people, nothing too fussy, and Maya doesn’t eat dairy.</UserBubble>
                <ActivityDisclosure label="3 activities" entries={activity} open />
                <AssistantMessage>
                  <p>I’d make lemony roast chicken with crispy potatoes and a big herby salad. It feels special without needing constant attention.</p>
                  <p><strong>Timing:</strong> shop at 5:30, start cooking at 6:15, and sit down around 7:20. I’ll keep every ingredient dairy-free.</p>
                </AssistantMessage>
                <UserBubble className={bubbles ? styles.accentBubble : styles.bubbleless}>Perfect. Add sparkling water and something chocolatey to the list.</UserBubble>
              </ConversationRail>
            </ConversationCanvas>
            <div className={styles.composerArea}>
              <ConversationComposer
                allyName="Sally"
                value={draft}
                placeholder="Message Sally"
                disabled={false}
                sending={false}
                onChange={setDraft}
                onSubmit={() => setDraft("")}
              />
            </div>
          </ConversationShell>
        </div>
      </section>
    </main>
  );
}
