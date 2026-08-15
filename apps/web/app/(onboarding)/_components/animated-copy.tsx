"use client";

import { TextLoader } from "generative-loaders";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import { ClickSpark, type SparkTrigger } from "./click-spark";

export type AllyKind = "red" | "blue" | "yellow" | "green";
export type AllyAnimationState = "idle" | "thinking";

export type CopyPart =
  | { type: "text"; text: string }
  | {
      type: "icon";
      word: string;
      color?: string;
      icon: ReactNode;
      iconAfter?: boolean;
    };

export type CopyParagraph = {
  ally: AllyKind | null;
  color: string;
  parts: CopyPart[];
};

/** A staged visit can reveal one or several adjacent copy lines. */
export type StoryBeat = {
  actor: AllyKind;
  paragraphs: number[];
  color: string;
};

type Position = { left: number; top: number };

type Phase =
  | { name: "intro" }
  | { name: "approach"; beatIndex: number }
  | { name: "press"; beatIndex: number }
  | { name: "reveal"; beatIndex: number }
  | { name: "hold"; beatIndex: number }
  | { name: "settle"; beatIndex: number }
  | { name: "converge" }
  | { name: "done" };

type ParkedActor = {
  id: string;
  ally: AllyKind;
  position: Position;
  roamX: number;
  roamY: number;
  delay: number;
};

const INTRO_MS = 520;
const APPROACH_MS = 920;
const PRESS_MS = 240;
const HOLD_MS = 620;
const SETTLE_MS = 420;
const CONVERGE_MS = 1050;
const REVEAL_MIN_MS = 860;
const REVEAL_MAX_MS = 1900;
const ROAM_OFFSETS: Record<AllyKind, Position> = {
  red: { left: 96, top: 46 },
  blue: { left: -86, top: 66 },
  yellow: { left: -72, top: -58 },
  green: { left: 88, top: -52 },
};

export function plainFrom(parts: CopyPart[]) {
  return parts
    .map((part) => (part.type === "text" ? part.text : part.word))
    .join("");
}

function revealMsFor(text: string) {
  return Math.min(
    REVEAL_MAX_MS,
    Math.max(REVEAL_MIN_MS, Array.from(text).length * 34),
  );
}

function cushion(t: number) {
  const clamped = Math.min(1, Math.max(0, t));
  return 1 - (1 - clamped) ** 3;
}

function IconWord({
  icon,
  word,
  color,
  iconAfter,
}: {
  icon: ReactNode;
  word: string;
  color?: string;
  iconAfter?: boolean;
}) {
  return (
    <span style={{ whiteSpace: "nowrap" }}>
      {!iconAfter && icon}
      <span style={color ? { color } : undefined}>{word}</span>
      {iconAfter && icon}
    </span>
  );
}

function SettledLine({ parts }: { parts: CopyPart[] }) {
  return (
    <>
      {parts.map((part, index) =>
        part.type === "text" ? (
          <span key={index}>{part.text}</span>
        ) : (
          <IconWord
            key={index}
            icon={part.icon}
            word={part.word}
            color={part.color}
            iconAfter={part.iconAfter}
          />
        ),
      )}
    </>
  );
}

function WipingLine({
  parts,
  revealChars,
  color,
  preserveIconColor = false,
}: {
  parts: CopyPart[];
  revealChars: number;
  color: string;
  preserveIconColor?: boolean;
}) {
  const nodes: ReactNode[] = [];
  let consumed = 0;

  for (const [index, part] of parts.entries()) {
    if (part.type === "icon") {
      const partLength = Array.from(part.word).length;
      const isVisible = revealChars - consumed >= partLength;
      const icon = (
        <IconWord
          icon={part.icon}
          word={part.word}
          color={preserveIconColor ? part.color ?? color : color}
          iconAfter={part.iconAfter}
        />
      );

      nodes.push(
        isVisible ? (
          <span key={index}>{icon}</span>
        ) : (
          <span
            key={index}
            aria-hidden="true"
            style={{ visibility: "hidden", whiteSpace: "nowrap" }}
          >
            {icon}
          </span>
        ),
      );
      consumed += partLength;
      continue;
    }

    const chars = Array.from(part.text);
    const take = Math.max(0, Math.min(chars.length, revealChars - consumed));
    const slice = chars.slice(0, take).join("");
    const isCurrent = take < chars.length;

    if (slice) {
      nodes.push(
        <TextLoader
          key={`${index}-visible`}
          text={slice}
          variant="coalesce"
          speed={1.2}
          color="currentColor"
          paused={!isCurrent}
          className="onboarding-copy-loader"
        />,
      );
    }

    if (isCurrent) {
      nodes.push(
        <span
          key={`${index}-reserve`}
          aria-hidden="true"
          style={{ visibility: "hidden", whiteSpace: "pre-wrap" }}
        >
          {chars.slice(take).join("")}
        </span>,
      );
    }

    consumed += chars.length;
  }

  return <>{nodes}</>;
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function activeBeatIndex(phase: Phase) {
  return phase.name === "approach" ||
    phase.name === "press" ||
    phase.name === "reveal" ||
    phase.name === "hold" ||
    phase.name === "settle"
    ? phase.beatIndex
    : null;
}

function actorEntryPosition(
  target: Position,
  beatIndex: number,
  hostWidth: number,
  hostHeight: number,
): Position {
  const fromRight = beatIndex % 2 === 1;
  return {
    left: fromRight ? hostWidth + 88 : -90,
    top: clamp(
      target.top + (beatIndex % 3 === 0 ? -30 : beatIndex % 3 === 1 ? 22 : -8),
      18,
      Math.max(18, hostHeight - 72),
    ),
  };
}

function fallbackTarget(index: number, hostWidth: number, hostHeight: number) {
  return {
    left: clamp(hostWidth * (0.24 + (index % 3) * 0.24), 12, Math.max(12, hostWidth - 74)),
    top: clamp(50 + index * 48, 16, Math.max(16, hostHeight - 76)),
  };
}

export function AnimatedCopy({
  paragraphs,
  paragraphGap,
  beats,
  initialParagraphs,
  renderActor,
  onComplete,
}: {
  paragraphs: CopyParagraph[];
  paragraphGap: number;
  beats?: StoryBeat[];
  initialParagraphs?: number[];
  renderActor: (ally: AllyKind, state: AllyAnimationState) => ReactNode;
  onComplete?: (done: boolean) => void;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const lineRefs = useRef<Array<HTMLDivElement | null>>([]);
  const sparkIdRef = useRef(0);
  const [phase, setPhase] = useState<Phase>({ name: "intro" });
  const [revealChars, setRevealChars] = useState(0);
  const [reducedMotion, setReducedMotion] = useState(false);
  const [targets, setTargets] = useState<Position[]>([]);
  const [hostSize, setHostSize] = useState({ width: 375, height: 812 });
  const [parked, setParked] = useState<ParkedActor[]>([]);
  const [completedBeatCount, setCompletedBeatCount] = useState(0);
  const [spark, setSpark] = useState<SparkTrigger | null>(null);
  const [arrivedBeat, setArrivedBeat] = useState<number | null>(null);
  const initialParagraphSet = useMemo(
    () => new Set(initialParagraphs ?? [0]),
    [initialParagraphs],
  );

  const storyBeats = useMemo<StoryBeat[]>(
    () =>
      beats?.length
        ? beats
        : paragraphs.map((paragraph, index) => ({
            actor: paragraph.ally ?? "red",
            paragraphs: [index],
            color: paragraph.color,
          })),
    [beats, paragraphs],
  );

  const beatForParagraph = useMemo(() => {
    const result = new Map<number, number>();
    storyBeats.forEach((beat, beatIndex) => {
      beat.paragraphs.forEach((paragraphIndex) =>
        result.set(paragraphIndex, beatIndex),
      );
    });
    return result;
  }, [storyBeats]);

  const getTargets = useCallback(() => {
    const host = hostRef.current;
    if (!host) return;

    const hostBox = host.getBoundingClientRect();
    setHostSize({ width: hostBox.width, height: hostBox.height });
    const next = storyBeats.map((beat, index) => {
      const line = lineRefs.current[beat.paragraphs[0]];
      if (!line) {
        return {
          left: hostBox.width * (0.24 + (index % 3) * 0.24),
          top: 50 + index * 48,
        };
      }

      const lineBox = line.getBoundingClientRect();
      const togetherIcon = line.querySelector<HTMLElement>(
        "[data-together-icon]",
      );
      const anchorBox = togetherIcon?.getBoundingClientRect();
      if (anchorBox) {
        return {
          left: clamp(
            anchorBox.left - hostBox.left - 6,
            12,
            Math.max(12, hostBox.width - 74),
          ),
          top: clamp(
            anchorBox.top - hostBox.top - 10,
            16,
            Math.max(16, hostBox.height - 76),
          ),
        };
      }
      const lineWidth = Math.max(40, lineBox.width);
      return {
        left: clamp(
          lineBox.left - hostBox.left + Math.min(lineWidth * 0.62, lineWidth - 36),
          12,
          Math.max(12, hostBox.width - 74),
        ),
        top: clamp(
          lineBox.top - hostBox.top + lineBox.height * 0.08 - 8,
          16,
          Math.max(16, hostBox.height - 76),
        ),
      };
    });
    setTargets(next);
  }, [storyBeats]);

  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReducedMotion(query.matches);
    update();
    query.addEventListener?.("change", update);
    return () => query.removeEventListener?.("change", update);
  }, []);

  useLayoutEffect(() => {
    getTargets();
    const host = hostRef.current;
    if (!host) return;

    const observer = new ResizeObserver(getTargets);
    observer.observe(host);
    window.addEventListener("resize", getTargets);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", getTargets);
    };
  }, [getTargets]);

  useEffect(() => {
    if (!reducedMotion) return;
    const frame = window.requestAnimationFrame(() => {
      setPhase({ name: "done" });
      setRevealChars(0);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [reducedMotion]);

  useEffect(() => {
    if (!reducedMotion) return;
    const frame = window.requestAnimationFrame(() => {
      setParked((current) => {
        const byAlly = new Map(current.map((actor) => [actor.ally, actor]));
        storyBeats.forEach((beat, index) => {
          byAlly.set(beat.actor, {
            id: `story-ally-${beat.actor}`,
            ally: beat.actor,
            position:
              targets[index] ?? fallbackTarget(index, hostSize.width, hostSize.height),
            roamX: 0,
            roamY: 0,
            delay: 0,
          });
        });
        return Array.from(byAlly.values());
      });
      setCompletedBeatCount(storyBeats.length);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [hostSize.height, hostSize.width, reducedMotion, storyBeats, targets]);

  useEffect(() => {
    if (reducedMotion || phase.name !== "intro") return;
    const id = window.setTimeout(() => {
      if (storyBeats.length === 0) {
        setPhase({ name: "done" });
      } else {
        setPhase({ name: "approach", beatIndex: 0 });
      }
    }, INTRO_MS);
    return () => window.clearTimeout(id);
  }, [phase, reducedMotion, storyBeats.length]);

  useEffect(() => {
    if (reducedMotion || phase.name !== "approach") return;
    const arrivalFrame = window.requestAnimationFrame(() => {
      setArrivedBeat(phase.beatIndex);
    });
    const id = window.setTimeout(
      () => setPhase({ name: "press", beatIndex: phase.beatIndex }),
      APPROACH_MS,
    );
    return () => {
      window.cancelAnimationFrame(arrivalFrame);
      window.clearTimeout(id);
    };
  }, [phase, reducedMotion]);

  useEffect(() => {
    if (reducedMotion || phase.name !== "press") return;
    const target =
      targets[phase.beatIndex] ??
      fallbackTarget(phase.beatIndex, hostSize.width, hostSize.height);

    const id = window.setTimeout(() => {
      sparkIdRef.current += 1;
      setSpark({
        id: sparkIdRef.current,
        // The cursor tip is the thing that lands on the copy, not the Ally's
        // face. Keep the spark on that tip so the click reads clearly.
        x: target.left + 5,
        y: target.top + 6,
      });
      setRevealChars(0);
      setPhase({ name: "reveal", beatIndex: phase.beatIndex });
    }, PRESS_MS);
    return () => window.clearTimeout(id);
  }, [hostSize.height, hostSize.width, phase, reducedMotion, targets]);

  useEffect(() => {
    if (reducedMotion || phase.name !== "reveal") return;
    const beat = storyBeats[phase.beatIndex];
    if (!beat) return;

    const text = beat.paragraphs
      .map((paragraphIndex) => plainFrom(paragraphs[paragraphIndex].parts))
      .join("");
    const chars = Array.from(text);
    const duration = revealMsFor(text);
    const started = performance.now();
    let frame = 0;
    let resetFrame = 0;

    const tick = (now: number) => {
      const progress = cushion((now - started) / duration);
      setRevealChars(Math.max(1, Math.round(progress * chars.length)));
      if (progress < 1) {
        frame = window.requestAnimationFrame(tick);
        return;
      }
      setRevealChars(chars.length);
      setPhase({ name: "hold", beatIndex: phase.beatIndex });
    };

    resetFrame = window.requestAnimationFrame(() => {
      setRevealChars(0);
      frame = window.requestAnimationFrame(tick);
    });
    return () => {
      window.cancelAnimationFrame(resetFrame);
      window.cancelAnimationFrame(frame);
    };
  }, [paragraphs, phase, reducedMotion, storyBeats]);

  useEffect(() => {
    if (reducedMotion || phase.name !== "hold") return;
    const id = window.setTimeout(
      () => setPhase({ name: "settle", beatIndex: phase.beatIndex }),
      HOLD_MS,
    );
    return () => window.clearTimeout(id);
  }, [phase, reducedMotion]);

  useEffect(() => {
    if (reducedMotion || phase.name !== "settle") return;
    const beat = storyBeats[phase.beatIndex];
    const target =
      targets[phase.beatIndex] ??
      fallbackTarget(phase.beatIndex, hostSize.width, hostSize.height);
    if (!beat) return;

    const id = window.setTimeout(() => {
      setParked((current) => [
        ...current.filter((actor) => actor.ally !== beat.actor),
        {
          id: `story-ally-${beat.actor}`,
          ally: beat.actor,
          position: target,
          roamX: ROAM_OFFSETS[beat.actor].left,
          roamY: ROAM_OFFSETS[beat.actor].top,
          delay: phase.beatIndex * 380,
        },
      ]);
      setCompletedBeatCount((current) =>
        Math.max(current, phase.beatIndex + 1),
      );

      const next = phase.beatIndex + 1;
      setPhase(
        next >= storyBeats.length
          ? { name: "converge" }
          : { name: "approach", beatIndex: next },
      );
    }, SETTLE_MS);
    return () => window.clearTimeout(id);
  }, [hostSize.height, hostSize.width, phase, reducedMotion, storyBeats, targets]);

  useEffect(() => {
    if (reducedMotion || phase.name !== "converge") return;
    const id = window.setTimeout(() => setPhase({ name: "done" }), CONVERGE_MS);
    return () => window.clearTimeout(id);
  }, [phase, reducedMotion]);

  useEffect(() => {
    onComplete?.(phase.name === "done");
  }, [onComplete, phase.name]);

  const currentBeat = activeBeatIndex(phase);
  const hostWidth = hostSize.width;
  const hostHeight = hostSize.height;
  const activeTarget =
    currentBeat == null
      ? null
      : targets[currentBeat] ??
        fallbackTarget(currentBeat, hostWidth, hostHeight);
  const activeParkedActor =
    currentBeat == null
      ? null
      : parked.find((actor) => actor.ally === storyBeats[currentBeat].actor);
  const activeEntry =
    currentBeat == null || !activeTarget
      ? null
      : activeParkedActor?.position ??
        actorEntryPosition(activeTarget, currentBeat, hostWidth, hostHeight);
  const activePosition =
    currentBeat == null || !activeTarget || !activeEntry
      ? null
      : arrivedBeat === currentBeat
        ? activeTarget
        : activeEntry;

  const currentRevealChars =
    phase.name === "reveal" || phase.name === "hold" || phase.name === "settle"
      ? revealChars
      : 0;
  const currentBeatTextLength =
    currentBeat == null
      ? 0
      : storyBeats[currentBeat].paragraphs.reduce(
          (total, paragraphIndex) =>
            total + Array.from(plainFrom(paragraphs[paragraphIndex].parts)).length,
        0,
        );

  const isConverging = phase.name === "converge" || phase.name === "done";
  const finalTarget =
    storyBeats.length > 0
      ? targets[storyBeats.length - 1] ??
        fallbackTarget(storyBeats.length - 1, hostWidth, hostHeight)
      : null;
  const convergenceOffsets: Record<AllyKind, Position> = {
    red: { left: -14, top: -6 },
    blue: { left: 4, top: -8 },
    yellow: { left: -3, top: 8 },
    green: { left: 15, top: 6 },
  };

  const actorState: AllyAnimationState =
    phase.name === "press" ||
    phase.name === "reveal" ||
    phase.name === "hold"
      ? "thinking"
      : "idle";

  return (
    <div
      ref={hostRef}
      data-story-phase={phase.name}
      data-story-beat={currentBeat ?? undefined}
      data-story-actor-order={storyBeats.map((beat) => beat.actor).join(",")}
      data-story-reduced-motion={reducedMotion ? "true" : "false"}
      style={{ position: "relative", width: "100%" }}
    >
      {paragraphs.map((paragraph, index) => {
        const beatIndex = beatForParagraph.get(index);
        const isComplete =
          initialParagraphSet.has(index) ||
          phase.name === "done" ||
          (beatIndex != null && beatIndex < completedBeatCount);
        const isCurrent = beatIndex === currentBeat;
        const showCurrent =
          isCurrent &&
          (phase.name === "reveal" ||
            phase.name === "hold" ||
            phase.name === "settle");

        let content: ReactNode;
        if (isComplete) {
          content = initialParagraphSet.has(index) ? (
            <SettledLine parts={paragraph.parts} />
          ) : (
            <span
              style={{
                color: "#121212",
                transition: "color 520ms ease",
              }}
            >
              <WipingLine
                parts={paragraph.parts}
                revealChars={Array.from(plainFrom(paragraph.parts)).length}
                color={paragraph.color}
                preserveIconColor
              />
            </span>
          );
        } else if (showCurrent && beatIndex != null) {
          const previousChars = storyBeats[beatIndex].paragraphs
            .slice(0, storyBeats[beatIndex].paragraphs.indexOf(index))
            .reduce(
              (total, paragraphIndex) =>
                total +
                Array.from(plainFrom(paragraphs[paragraphIndex].parts)).length,
              0,
            );
          const paragraphChars = Array.from(plainFrom(paragraph.parts)).length;
          content = (
            <span
              style={{
                color: storyBeats[beatIndex].color,
                transition: "color 520ms ease",
              }}
            >
              <WipingLine
                parts={paragraph.parts}
                revealChars={
                  phase.name === "hold" || phase.name === "settle"
                    ? paragraphChars
                    : Math.max(
                        0,
                        Math.min(
                          paragraphChars,
                          currentRevealChars - previousChars,
                        ),
                      )
                }
                color={storyBeats[beatIndex].color}
              />
            </span>
          );
        } else {
          content = (
            <span
              aria-hidden="true"
              style={{ visibility: "hidden", color: "#121212" }}
            >
              <WipingLine
                parts={paragraph.parts}
                revealChars={Array.from(plainFrom(paragraph.parts)).length}
                color={paragraph.color}
                preserveIconColor
              />
            </span>
          );
        }

        return (
          <div
            key={index}
            ref={(node) => {
              lineRefs.current[index] = node;
            }}
            className="text"
            style={{
              display: "block",
              width: "100%",
              minHeight: "1em",
              margin: 0,
              marginBottom:
                index < paragraphs.length - 1 ? paragraphGap : 0,
              position: "relative",
            }}
          >
            {content}
          </div>
        );
      })}

      <div
        data-story-actors
        style={{
          position: "absolute",
          inset: 0,
          pointerEvents: "none",
          zIndex: 3,
          overflow: "visible",
        }}
      >
        {parked.map((actor) => {
          const isActiveActor =
            !isConverging &&
            currentBeat != null &&
            storyBeats[currentBeat].actor === actor.ally;
          if (isActiveActor) return null;

          return (
            <div
              key={actor.id}
              data-story-parked={actor.id}
              data-story-converged={
                isConverging ? "true" : undefined
              }
              data-ally={actor.ally}
              className="story-ally story-ally-parked"
              style={(() => {
                const offset = convergenceOffsets[actor.ally];
                const convergencePosition = finalTarget
                  ? {
                      left: finalTarget.left + offset.left,
                      top: finalTarget.top + offset.top,
                    }
                  : actor.position;
                return {
                  position: "absolute",
                  left: isConverging
                    ? convergencePosition.left
                    : actor.position.left,
                  top: isConverging
                    ? convergencePosition.top
                    : actor.position.top,
                  opacity: 1,
                  animationName: isConverging ? "none" : "story-ally-roam",
                  animationDelay: `${actor.delay}ms`,
                  animationDuration: `${5.2 + actor.delay / 1000}s`,
                  transform: isConverging ? "scale(0.42)" : undefined,
                  transformOrigin: "12px 22px",
                  transition: isConverging
                    ? `left ${CONVERGE_MS}ms cubic-bezier(.22,1,.36,1), top ${CONVERGE_MS}ms cubic-bezier(.22,1,.36,1), transform ${CONVERGE_MS}ms cubic-bezier(.22,1,.36,1), opacity 300ms ease`
                    : undefined,
                  "--story-roam-x": `${actor.roamX}px`,
                  "--story-roam-y": `${actor.roamY}px`,
                } as CSSProperties;
              })()}
            >
              {renderActor(actor.ally, "idle")}
            </div>
          );
        })}

        {currentBeat != null && activePosition && activeTarget ? (
          <div
            data-story-actor
            data-story-actor-index={currentBeat}
            data-story-actor-state={actorState}
            className="story-ally story-ally-active"
            style={{
              position: "absolute",
              left: 0,
              top: 0,
              transform: `translate3d(${activePosition.left}px, ${activePosition.top}px, 0) rotate(${arrivedBeat === currentBeat ? 0 : currentBeat % 2 === 0 ? -8 : 8}deg)`,
              transition:
                arrivedBeat === currentBeat
                  ? `transform ${APPROACH_MS}ms cubic-bezier(.22,1,.36,1)`
                  : "none",
            }}
          >
            {renderActor(storyBeats[currentBeat].actor, actorState)}
          </div>
        ) : null}

        <ClickSpark trigger={reducedMotion ? null : spark} sparkColor="#121212" />
      </div>
      <span
        data-story-progress
        aria-hidden="true"
        style={{
          position: "absolute",
          width: 1,
          height: 1,
          overflow: "hidden",
          clipPath: "inset(50%)",
        }}
      >
        {currentBeat != null && currentBeatTextLength > 0
          ? `${currentRevealChars}/${currentBeatTextLength}`
          : ""}
      </span>
    </div>
  );
}
