"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  ALLY_ANIMATION_CYCLE_MS,
  ALLY_ANIMATION_STATES,
  ALLY_MOTION_MODES,
  ALLY_SHAPES,
  AllyAvatar,
  DEFAULT_ALLY_COLOR,
  getAllyAsset,
  normalizeAllyColor,
  type AllyAnimationState,
  type AllyMotionMode,
  type AllyShape,
} from "@/components/ally-avatar";
import styles from "./animation-playground.module.css";

const SHAPE_LABELS: Record<AllyShape, string> = {
  boxy: "Boxy",
  ghosty: "Ghosty",
  rocky: "Rocky",
  rolly: "Rolly",
};

const SHAPE_ACCENTS: Record<AllyShape, string> = {
  boxy: "#fbe65f",
  ghosty: "#fd304f",
  rocky: "#12c25b",
  rolly: "#3446e9",
};

const COLOR_SWATCHES = [
  "#FF5800",
  "#3446E9",
  "#FD304F",
  "#12C25B",
  "#FBE65F",
  "#A88BEA",
] as const;

const HEX_COLOR = /^#(?:[\da-f]{3}|[\da-f]{4}|[\da-f]{6}|[\da-f]{8})$/i;

function formatState(state: string) {
  return ({ idle: "Idle", thinking: "Thinking", sleeping: "Sleeping", waking: "Waking", "falling-asleep": "Falling asleep" } as Record<string, string>)[state] ?? "Idle";
}

function formatMotion(mode: AllyMotionMode) {
  if (mode === "full") return "Full motion";
  if (mode === "reduced") return "Reduced motion";
  return "System preference";
}

export default function AnimationPlayground() {
  const [shape, setShape] = useState<AllyShape>("ghosty");
  const [requestedState, setRequestedState] =
    useState<AllyAnimationState>("idle");
  const [motionMode, setMotionMode] = useState<AllyMotionMode>("full");
  const [colorDraft, setColorDraft] = useState(DEFAULT_ALLY_COLOR);
  const [activeState, setActiveState] =
    useState<string>(requestedState);
  const [events, setEvents] = useState([
    "Ready — waiting for a state request",
  ]);
  const stageRef = useRef<HTMLDivElement>(null);
  const activeStateRef = useRef<string>(requestedState);

  const activeColor = normalizeAllyColor(colorDraft);
  const colorIsValid = HEX_COLOR.test(colorDraft.trim());
  const pickerColor =
    /^#[\da-f]{6}$/i.test(colorDraft.trim()) && colorIsValid
      ? colorDraft
      : /^#[\da-f]{6}$/i.test(activeColor)
        ? activeColor
        : DEFAULT_ALLY_COLOR;
  const assetPath = getAllyAsset(
    shape,
    requestedState,
    motionMode === "reduced",
  );

  const recordEvent = useCallback((message: string) => {
    setEvents((current) => [message, ...current].slice(0, 5));
  }, []);

  useEffect(() => {
    const avatar = stageRef.current?.querySelector<HTMLElement>(
      "[data-ally-avatar]",
    );
    if (!avatar) return;

    const syncFromAvatar = () => {
      const nextState = avatar.dataset.allyState ?? "idle";
      if (nextState === activeStateRef.current) return;
      activeStateRef.current = nextState;
      setActiveState(nextState);
      recordEvent(`Active state → ${formatState(nextState)}`);
    };

    syncFromAvatar();
    const observer = new MutationObserver((records) => {
      if (
        records.some(
          (record) =>
            record.type === "attributes" &&
            record.attributeName === "data-ally-state",
        )
      ) {
        syncFromAvatar();
      }
    });
    observer.observe(avatar, {
      attributes: true,
      attributeFilter: ["data-ally-state"],
    });

    return () => observer.disconnect();
  }, [motionMode, recordEvent, shape]);

  const reset = () => {
    setShape("ghosty");
    setRequestedState("idle");
    setMotionMode("full");
    setColorDraft(DEFAULT_ALLY_COLOR);
    setEvents(["Reset — ready for a new animation check"]);
  };

  const swapState = () => {
    const nextState = requestedState === "idle" ? "thinking" : "idle";
    setRequestedState(nextState);
    recordEvent(
      `Requested ${formatState(nextState)} — waits for the current cycle`,
    );
  };

  const selectedAssetLabel = useMemo(
    () => assetPath.replace(/^\//, ""),
    [assetPath],
  );

  return (
    <main className={styles.page} data-testid="animation-playground">
      <div className={styles.shell}>
        <header className={styles.header}>
          <div className={styles.brandLockup}>
            <span className={styles.brandMark} aria-hidden="true">
              <span />
            </span>
            <span>allies</span>
          </div>
          <div className={styles.environment}>
            <span className={styles.environmentDot} />
            debug / animation
          </div>
        </header>

        <section className={styles.intro}>
          <p className={styles.eyebrow}>Animation lab · internal</p>
          <h1>See an Ally come to life.</h1>
          <p className={styles.introCopy}>
            A small, honest playground for checking shapes, shell colors, and
            state changes before they land in the waitlist experience.
          </p>
        </section>

        <div className={styles.workspace}>
          <section className={styles.stageColumn} aria-label="Live preview">
            <div className={styles.stage} ref={stageRef} data-testid="animation-stage">
              <div className={styles.stageHeader}>
                <div>
                  <span className={styles.stageLabel}>Live preview</span>
                  <span className={styles.stageSubLabel}>
                    boundary-synced state machine
                  </span>
                </div>
                <span className={styles.statusPill}>
                  <span className={styles.statusPulse} />
                  running
                </span>
              </div>

              <div className={styles.stageCanvas}>
                <div className={styles.canvasCrosshair} aria-hidden="true" />
                <div className={styles.canvasCorner} aria-hidden="true">
                  <span>470 × 470</span>
                  <span>SVG / external document</span>
                </div>
                <AllyAvatar
                  shape={shape}
                  state={requestedState}
                  motion={motionMode}
                  color={colorDraft}
                  size="min(42vw, 280px)"
                  label={`${SHAPE_LABELS[shape]} Ally preview`}
                />
                <div className={styles.canvasCaption}>
                  <span>{SHAPE_LABELS[shape]}</span>
                  <span className={styles.captionDivider}>/</span>
                  <span>{formatState(activeState)}</span>
                </div>
              </div>

              <div className={styles.stageFooter}>
                <div>
                  <span className={styles.footerLabel}>Requested</span>
                  <strong>{formatState(requestedState)}</strong>
                </div>
                <div>
                  <span className={styles.footerLabel}>Active</span>
                  <strong>{formatState(activeState)}</strong>
                </div>
                <div>
                  <span className={styles.footerLabel}>Shell</span>
                  <strong className={styles.colorValue}>
                    <span style={{ backgroundColor: activeColor }} />
                    {activeColor}
                  </strong>
                </div>
              </div>
            </div>

            <div className={styles.inspectorStrip}>
              <div>
                <span className={styles.inspectorLabel}>Asset source</span>
                <code>{selectedAssetLabel}</code>
              </div>
              <div>
                <span className={styles.inspectorLabel}>Mode</span>
                <code>{formatMotion(motionMode)}</code>
              </div>
            </div>
          </section>

          <aside className={styles.controls} aria-label="Animation controls">
            <section className={styles.controlSection}>
              <div className={styles.sectionHeading}>
                <span className={styles.sectionNumber}>01</span>
                <h2>Choose a shape</h2>
              </div>
              <div className={styles.shapeGrid}>
                {ALLY_SHAPES.map((option) => (
                  <button
                    className={`${styles.shapeButton} ${
                      shape === option ? styles.selected : ""
                    }`}
                    data-testid={`shape-${option}`}
                    key={option}
                    type="button"
                    aria-pressed={shape === option}
                    onClick={() => setShape(option)}
                  >
                    <AllyAvatar
                      shape={option}
                      motion="reduced"
                      color={SHAPE_ACCENTS[option]}
                      size={48}
                      label={`${SHAPE_LABELS[option]} shape`}
                    />
                    <span>{SHAPE_LABELS[option]}</span>
                  </button>
                ))}
              </div>
            </section>

            <section className={styles.controlSection}>
              <div className={styles.sectionHeading}>
                <span className={styles.sectionNumber}>02</span>
                <h2>Request a state</h2>
              </div>
              <div className={styles.segmentedControl} role="group" aria-label="Animation state">
                {ALLY_ANIMATION_STATES.map((option) => (
                  <button
                    className={requestedState === option ? styles.activeSegment : ""}
                    data-testid={`state-${option}`}
                    key={option}
                    type="button"
                    aria-pressed={requestedState === option}
                    onClick={() => {
                      setRequestedState(option);
                      recordEvent(
                        `Requested ${formatState(option)} — waits for the current cycle`,
                      );
                    }}
                  >
                    {formatState(option)}
                    <span>{(ALLY_ANIMATION_CYCLE_MS[option] / 1000).toFixed(3)}s</span>
                  </button>
                ))}
              </div>
              <button className={styles.swapButton} type="button" onClick={swapState}>
                <span>Swap state</span>
                <span aria-hidden="true">↗</span>
              </button>
              <p className={styles.helperText}>
                State changes wait for the active SVG loop to finish. Tap swap
                repeatedly to exercise latest-request-wins behavior.
              </p>
            </section>

            <section className={styles.controlSection}>
              <div className={styles.sectionHeading}>
                <span className={styles.sectionNumber}>03</span>
                <h2>Paint the shell</h2>
              </div>
              <div className={styles.colorInputRow}>
                <label className={styles.colorField}>
                  <span className={styles.visuallyHidden}>Hex shell color</span>
                  <input
                    value={colorDraft}
                    onChange={(event) => setColorDraft(event.target.value)}
                    spellCheck={false}
                    aria-label="Hex shell color"
                    data-testid="hex-color-input"
                  />
                </label>
                <label className={styles.colorPicker}>
                  <span className={styles.visuallyHidden}>Pick a shell color</span>
                  <input
                    type="color"
                    value={pickerColor}
                    onChange={(event) => setColorDraft(event.target.value.toUpperCase())}
                    aria-label="Pick a shell color"
                  />
                </label>
              </div>
              <div className={styles.swatches} aria-label="Color shortcuts">
                {COLOR_SWATCHES.map((swatch) => (
                  <button
                    key={swatch}
                    className={styles.swatch}
                    type="button"
                    aria-label={`Use ${swatch}`}
                    aria-pressed={activeColor.toUpperCase() === swatch}
                    style={{ backgroundColor: swatch }}
                    onClick={() => setColorDraft(swatch)}
                  />
                ))}
              </div>
              <p className={styles.helperText}>
                Accepts #RGB, #RGBA, #RRGGBB, and #RRGGBBAA. Invalid values
                fall back to {DEFAULT_ALLY_COLOR}.
                {!colorIsValid && <strong> Fallback is active.</strong>}
              </p>
            </section>

            <section className={styles.controlSection}>
              <div className={styles.sectionHeading}>
                <span className={styles.sectionNumber}>04</span>
                <h2>Test motion</h2>
              </div>
              <div className={styles.motionGrid} role="group" aria-label="Motion preference">
                {ALLY_MOTION_MODES.map((option) => (
                  <button
                    className={motionMode === option ? styles.activeMotion : ""}
                    data-testid={`motion-${option}`}
                    key={option}
                    type="button"
                    aria-pressed={motionMode === option}
                    onClick={() => setMotionMode(option)}
                  >
                    {option}
                  </button>
                ))}
              </div>
              <p className={styles.helperText}>
                Full and reduced modes override the OS preference for this
                preview. System follows the browser setting.
              </p>
            </section>

            <div className={styles.actions}>
              <button className={styles.resetButton} type="button" onClick={reset}>
                Reset playground
              </button>
            </div>
          </aside>
        </div>

        <section className={styles.timeline} aria-label="Animation event log">
          <div className={styles.timelineHeading}>
            <div>
              <p className={styles.eyebrow}>Signal monitor</p>
              <h2>What the component is doing</h2>
            </div>
            <span className={styles.timelineMeta}>latest 5 events</span>
          </div>
          <div className={styles.timelineGrid}>
            <div className={styles.eventList}>
              {events.map((event, index) => (
                <div className={styles.event} key={`${event}-${index}`}>
                  <span className={styles.eventIndex}>{String(index + 1).padStart(2, "0")}</span>
                  <span>{event}</span>
                </div>
              ))}
            </div>
            <div className={styles.contractNote}>
              <span className={styles.contractKicker}>Current contract</span>
              <p>
                Shapes jump immediately. Shell colors transition. Animation
                state changes wait for the current authored loop boundary.
              </p>
              <div className={styles.loopRows}>
                {ALLY_ANIMATION_STATES.map((option) => (
                  <div key={option}>
                    <span>{formatState(option)}</span>
                    <strong>{(ALLY_ANIMATION_CYCLE_MS[option] / 1000).toFixed(3)}s</strong>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        <footer className={styles.footer}>
          <span>Allies interface / internal tooling</span>
          <span>Debug routes are hidden outside development and staging.</span>
        </footer>
      </div>
    </main>
  );
}
