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
import { arc, motion, type Transition } from "motion/react";
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

export type StoryActorBounds = {
  width: number;
  height: number;
  offsetLeft: number;
  offsetTop: number;
};

type Phase =
  | { name: "intro" }
  | { name: "approach"; beatIndex: number }
  | { name: "press"; beatIndex: number }
  | { name: "reveal"; beatIndex: number }
  | { name: "hold"; beatIndex: number }
  | { name: "settle"; beatIndex: number }
  | { name: "converge"; beatIndex: number; startPosition: Position }
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
const DESKTOP_APPROACH_MS = 1880;
const MOBILE_APPROACH_MS = 1540;
const PRESS_MS = 240;
const HOLD_MS = 620;
const DESKTOP_DEPART_MS = 1100;
const MOBILE_DEPART_MS = 860;
const DESKTOP_CONVERGE_MS = 1500;
const MOBILE_CONVERGE_MS = 1180;
const DESKTOP_CLICK_Y_OFFSET = 36;
const MOBILE_CLICK_Y_OFFSET = 32;
const REVEAL_MIN_MS = 1200;
const REVEAL_MAX_MS = 2800;
const DEFAULT_ROAM_OFFSETS: Record<AllyKind, Position> = {
  red: { left: 44, top: 24 },
  blue: { left: -40, top: 32 },
  yellow: { left: -34, top: -26 },
  green: { left: 38, top: -22 },
};

const ALLY_ANIMATION_DELAYS: Record<AllyKind, string> = {
  red: "-320ms",
  blue: "-760ms",
  yellow: "-1180ms",
  green: "-1540ms",
};

const DESKTOP_RESTING_POSITIONS: Position[] = [
  { left: 84, top: 132 },
  { left: 1350, top: 198 },
  { left: 72, top: 352 },
  { left: 1345, top: 474 },
  { left: 90, top: 626 },
  { left: 1335, top: 744 },
  { left: 180, top: 850 },
  { left: 1320, top: 866 },
];

const MOBILE_RESTING_POSITIONS: Position[] = [
  { left: 340, top: 126 },
  { left: 340, top: 208 },
  { left: -14, top: 314 },
  { left: 340, top: 430 },
  { left: -14, top: 536 },
  { left: 340, top: 642 },
  { left: -14, top: 708 },
  { left: 340, top: 752 },
];

// Parked Allies can wander by as much as the largest per-Ally roam offset.
// Keep that whole visual footprint inside the artboard; the artboard itself
// still clips deliberate off-canvas entry/exit movement.
const RESTING_ACTOR_SIZE = 60;
const RESTING_HORIZONTAL_MARGIN = 4;
const RESTING_VERTICAL_MARGIN = 4;

const CONVERGENCE_OFFSETS: Record<AllyKind, Position> = {
  yellow: { left: -9, top: -9 },
  blue: { left: 9, top: -9 },
  green: { left: -9, top: 9 },
  red: { left: 9, top: 9 },
};

function roamingBounds(viewportWidth: number, viewportHeight: number) {
  const isMobile = viewportWidth <= 500;
  const horizontalTravel = isMobile ? 32 : 44;
  const verticalTravel = isMobile ? 26 : 32;
  const horizontalInset = horizontalTravel + RESTING_HORIZONTAL_MARGIN;
  const verticalInset = verticalTravel + RESTING_VERTICAL_MARGIN;

  return {
    minLeft: horizontalInset,
    maxLeft: Math.max(
      horizontalInset,
      viewportWidth - RESTING_ACTOR_SIZE - horizontalInset,
    ),
    minTop: verticalInset,
    maxTop: Math.max(
      verticalInset,
      viewportHeight - RESTING_ACTOR_SIZE - verticalInset,
    ),
  };
}

export function plainFrom(parts: CopyPart[]) {
  return parts
    .map((part) => (part.type === "text" ? part.text : part.word))
    .join("");
}

function revealMsFor(text: string) {
  return Math.min(
    REVEAL_MAX_MS,
    Math.max(REVEAL_MIN_MS, Array.from(text).length * 48),
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
          <WordSafeText key={index} text={part.text} />
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

function WordSafeText({ text }: { text: string }) {
  const tokens = text.match(/\s+|\S+/g) ?? [];

  return (
    <>
      {tokens.map((token, index) => {
        const isWhitespace = /^\s+$/u.test(token);
        return (
          <span
            key={index}
            style={{
              display: isWhitespace ? "inline" : "inline-block",
              whiteSpace: isWhitespace ? "normal" : "nowrap",
              wordBreak: "keep-all",
              overflowWrap: "normal",
            }}
          >
            {token}
          </span>
        );
      })}
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

    const tokens = part.text.match(/\s+|\S+/g) ?? [];
    for (const [tokenIndex, token] of tokens.entries()) {
      const chars = Array.from(token);
      const take = Math.max(
        0,
        Math.min(chars.length, revealChars - consumed),
      );
      const slice = chars.slice(0, take).join("");
      const remainder = chars.slice(take).join("");
      const isWhitespace = /^\s+$/u.test(token);
      const isCurrent = take < chars.length;

      nodes.push(
        <span
          key={`${index}-${tokenIndex}`}
          style={{
            display: isWhitespace ? "inline" : "inline-block",
            whiteSpace: isWhitespace ? "normal" : "nowrap",
            wordBreak: "keep-all",
            overflowWrap: "normal",
          }}
        >
          {slice ? (
            isWhitespace ? (
              slice
            ) : (
              <TextLoader
                text={slice}
                variant="coalesce"
                speed={1.2}
                color="currentColor"
                paused={!isCurrent}
                className="onboarding-copy-loader"
              />
            )
          ) : null}
          {remainder ? (
            <span aria-hidden="true" style={{ visibility: "hidden" }}>
              {remainder}
            </span>
          ) : null}
        </span>,
      );

      consumed += chars.length;
    }
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
    phase.name === "settle" ||
    phase.name === "converge"
    ? phase.beatIndex
    : null;
}

function actorEntryPosition(
  target: Position,
  beatIndex: number,
  viewportWidth: number,
  viewportHeight: number,
): Position {
  const fromRight = beatIndex % 2 === 1;
  return {
    left: fromRight ? viewportWidth + 88 : -90,
    top: clamp(
      target.top + (beatIndex % 3 === 0 ? -30 : beatIndex % 3 === 1 ? 22 : -8),
      18,
      Math.max(18, viewportHeight - 72),
    ),
  };
}

function fallbackTarget(index: number, viewportWidth: number, viewportHeight: number) {
  return {
    left: clamp(
      viewportWidth * (0.24 + (index % 3) * 0.24),
      12,
      Math.max(12, viewportWidth - 74),
    ),
    top: clamp(50 + index * 48, 16, Math.max(16, viewportHeight - 76)),
  };
}

function restingPosition(index: number, viewportWidth: number, viewportHeight: number) {
  const slots = viewportWidth <= 500
    ? MOBILE_RESTING_POSITIONS
    : DESKTOP_RESTING_POSITIONS;
  const slot = slots[index % slots.length];
  const bounds = roamingBounds(viewportWidth, viewportHeight);

  return {
    left: clamp(slot.left, bounds.minLeft, bounds.maxLeft),
    top: clamp(slot.top, bounds.minTop, bounds.maxTop),
  };
}

function roamKeyframes(
  actor: ParkedActor,
  viewportWidth: number,
  viewportHeight: number,
) {
  const { left, top } = actor.position;
  const { roamX, roamY } = actor;
  const bounds = roamingBounds(viewportWidth, viewportHeight);
  const safeX = (value: number) =>
    clamp(value, bounds.minLeft, bounds.maxLeft);
  const safeY = (value: number) => clamp(value, bounds.minTop, bounds.maxTop);

  return {
    x: [
      left,
      left + roamX * 0.35,
      left + roamX,
      left + roamX * 0.18,
      left - roamX * 0.72,
      left - roamX * 0.28,
      left,
    ].map(safeX),
    y: [
      top,
      top - roamY * 0.15,
      top + roamY * 0.3,
      top - roamY * 0.55,
      top + roamY * 0.35,
      top - roamY * 0.18,
      top,
    ].map(safeY),
    rotate: [0, 0.4, 0.7, -0.45, -0.75, -0.2, 0],
  };
}

const TRAVEL_EASE = "easeInOut" as const;

function travelTransition(
  duration: number,
  path: ReturnType<typeof arc>,
  reducedMotion: boolean,
  curved = true,
): Transition {
  return reducedMotion
    ? { duration: 0 }
    : {
        type: "tween",
        duration: duration / 1000,
        ease: TRAVEL_EASE,
        ...(curved ? { path } : {}),
      };
}

export function AnimatedCopy({
  paragraphs,
  paragraphGap,
  beats,
  initialParagraphs,
  actorBounds,
  artboardScale = 1,
  roamOffsets = DEFAULT_ROAM_OFFSETS,
  renderActor,
  onComplete,
  skipRequest = 0,
}: {
  paragraphs: CopyParagraph[];
  paragraphGap: number;
  beats?: StoryBeat[];
  initialParagraphs?: number[];
  actorBounds?: StoryActorBounds;
  artboardScale?: number;
  roamOffsets?: Record<AllyKind, Position>;
  renderActor: (
    ally: AllyKind,
    state: AllyAnimationState,
    options?: { hideCursor?: boolean },
  ) => ReactNode;
  onComplete?: (done: boolean) => void;
  skipRequest?: number;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const lineRefs = useRef<Array<HTMLDivElement | null>>([]);
  const targetsRef = useRef<Position[]>([]);
  const sparkIdRef = useRef(0);
  const [phase, setPhase] = useState<Phase>({ name: "intro" });
  const [revealChars, setRevealChars] = useState(0);
  const [reducedMotion, setReducedMotion] = useState(false);
  const [targets, setTargets] = useState<Position[]>([]);
  const [hostSize, setHostSize] = useState({ width: 375, height: 812 });
  const [parked, setParked] = useState<ParkedActor[]>([]);
  const [completedBeatCount, setCompletedBeatCount] = useState(0);
  const [spark, setSpark] = useState<SparkTrigger | null>(null);
  const [sparkColor, setSparkColor] = useState("#121212");
  const [parkedPositions, setParkedPositions] = useState<
    Partial<Record<AllyKind, Position>>
  >({});
  const actorWidth = actorBounds?.width ?? hostSize.width;
  const actorHeight = actorBounds?.height ?? hostSize.height;
  const actorOffsetLeft = actorBounds?.offsetLeft ?? 0;
  const actorOffsetTop = actorBounds?.offsetTop ?? 0;
  const approachDuration =
    actorWidth <= 500 ? MOBILE_APPROACH_MS : DESKTOP_APPROACH_MS;
  const departDuration = actorWidth <= 500 ? MOBILE_DEPART_MS : DESKTOP_DEPART_MS;
  const convergeDuration =
    actorWidth <= 500 ? MOBILE_CONVERGE_MS : DESKTOP_CONVERGE_MS;
  const clickYOffset =
    actorWidth <= 500 ? MOBILE_CLICK_Y_OFFSET : DESKTOP_CLICK_Y_OFFSET;
  const convergenceScale = actorWidth <= 500 ? 0.64 : 0.72;
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

  const travelArcs = useMemo(
    () => {
      const strength = actorWidth <= 500 ? 0.18 : 0.24;
      return [
        arc({ direction: "cw", rotate: 0.12, strength }),
        arc({ direction: "ccw", rotate: 0.12, strength }),
      ];
    },
    [actorWidth],
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
    const coordinateScale = artboardScale > 0 ? artboardScale : 1;
    setHostSize({ width: hostBox.width, height: hostBox.height });
    const next = storyBeats.map((beat, index) => {
      const line = lineRefs.current[beat.paragraphs[0]];
      if (!line) {
        return {
          left:
            actorOffsetLeft +
            (hostBox.width / coordinateScale) *
              (0.24 + (index % 3) * 0.24),
          top:
            actorOffsetTop +
            (50 + index * 48) / coordinateScale,
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
            (anchorBox.left - hostBox.left) / coordinateScale +
              actorOffsetLeft -
              6,
            12,
            Math.max(12, actorWidth - 74),
          ),
          top: clamp(
            (anchorBox.top - hostBox.top) / coordinateScale +
              actorOffsetTop -
              10,
            16,
            Math.max(16, actorHeight - 76),
          ),
        };
      }
      const lineWidth = Math.max(40, lineBox.width / coordinateScale);
      return {
        left: clamp(
          (lineBox.left - hostBox.left) / coordinateScale +
            actorOffsetLeft +
            Math.min(12, lineWidth * 0.06),
          12,
          Math.max(12, actorWidth - 74),
        ),
        top: clamp(
          (lineBox.top - hostBox.top) / coordinateScale +
            actorOffsetTop +
            (lineBox.height / coordinateScale) * 0.08 -
            8,
          16,
          Math.max(16, actorHeight - 76),
        ),
      };
    });
    targetsRef.current = next;
    setTargets(next);
  }, [
    actorHeight,
    actorOffsetLeft,
    actorOffsetTop,
    actorWidth,
    artboardScale,
    storyBeats,
  ]);

  const parkAllActors = useCallback(() => {
    const finalTarget =
      targetsRef.current[storyBeats.length - 1] ??
      fallbackTarget(storyBeats.length - 1, actorWidth, actorHeight);

    setParked((current) => {
      const byAlly = new Map(current.map((actor) => [actor.ally, actor]));
      storyBeats.forEach((beat) => {
        const offset = CONVERGENCE_OFFSETS[beat.actor];
        byAlly.set(beat.actor, {
          id: `story-ally-${beat.actor}`,
          ally: beat.actor,
          position: {
            left: finalTarget.left + offset.left,
            top: finalTarget.top + offset.top,
          },
          roamX: 0,
          roamY: 0,
          delay: 0,
        });
      });
      return Array.from(byAlly.values());
    });
    setCompletedBeatCount(storyBeats.length);
  }, [actorHeight, actorWidth, storyBeats]);

  const completeStory = useCallback(() => {
    setPhase({ name: "done" });
    setRevealChars(0);
    parkAllActors();
  }, [parkAllActors]);

  useEffect(() => {
    const query = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!query) return;

    const update = () => setReducedMotion(query.matches);
    update();
    query.addEventListener?.("change", update);
    return () => query.removeEventListener?.("change", update);
  }, []);

  useLayoutEffect(() => {
    getTargets();
    const host = hostRef.current;
    if (!host) return;

    const observer =
      typeof ResizeObserver === "function"
        ? new ResizeObserver(getTargets)
        : null;
    observer?.observe(host);
    window.addEventListener("resize", getTargets);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", getTargets);
    };
  }, [getTargets]);

  useEffect(() => {
    if (!reducedMotion) return;
    const frame = window.requestAnimationFrame(completeStory);
    return () => window.cancelAnimationFrame(frame);
  }, [completeStory, reducedMotion]);

  useEffect(() => {
    if (!skipRequest) return;
    const timer = window.setTimeout(completeStory, 0);
    return () => window.clearTimeout(timer);
  }, [completeStory, skipRequest]);

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
    const id = window.setTimeout(
      () => setPhase({ name: "press", beatIndex: phase.beatIndex }),
      approachDuration,
    );
    return () => window.clearTimeout(id);
  }, [approachDuration, phase, reducedMotion]);

  useEffect(() => {
    if (reducedMotion || phase.name !== "press") return;
    const beat = storyBeats[phase.beatIndex];
    if (!beat) return;
    const target =
      targets[phase.beatIndex] ??
      fallbackTarget(phase.beatIndex, actorWidth, actorHeight);
    const clickTarget = { ...target, top: target.top + clickYOffset };

    const id = window.setTimeout(() => {
      sparkIdRef.current += 1;
      setSparkColor(beat.color);
      setSpark({
        id: sparkIdRef.current,
        // The cursor tip is the thing that lands on the copy, not the Ally's
        // face. Keep the spark on that tip so the click reads clearly.
        x: clickTarget.left + 5,
        y: clickTarget.top + 6,
      });
      setRevealChars(0);
      setPhase({ name: "reveal", beatIndex: phase.beatIndex });
    }, PRESS_MS);
    return () => window.clearTimeout(id);
  }, [
    actorHeight,
    actorWidth,
    clickYOffset,
    phase,
    reducedMotion,
    storyBeats,
    targets,
  ]);

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
    const target =
      targets[phase.beatIndex] ??
      fallbackTarget(phase.beatIndex, actorWidth, actorHeight);
    const clickTarget = {
      left: target.left,
      top: target.top + clickYOffset,
    };
    const nextPhase: Phase =
      phase.beatIndex === storyBeats.length - 1
        ? {
            name: "converge",
            beatIndex: phase.beatIndex,
            startPosition: clickTarget,
          }
        : { name: "settle", beatIndex: phase.beatIndex };
    const id = window.setTimeout(
      () => setPhase(nextPhase),
      HOLD_MS,
    );
    return () => window.clearTimeout(id);
  }, [actorHeight, actorWidth, clickYOffset, phase, reducedMotion, storyBeats.length, targets]);

  useEffect(() => {
    if (reducedMotion || phase.name !== "settle") return;
    const beat = storyBeats[phase.beatIndex];
    if (!beat) return;

    const id = window.setTimeout(() => {
      const next = phase.beatIndex + 1;
      const position = restingPosition(
        phase.beatIndex,
        actorWidth,
        actorHeight,
      );
      setParkedPositions((current) => ({
        ...current,
        [beat.actor]: position,
      }));
      setParked((current) => [
        ...current.filter((actor) => actor.ally !== beat.actor),
        {
          id: `story-ally-${beat.actor}`,
          ally: beat.actor,
          position,
          roamX: roamOffsets[beat.actor].left,
          roamY: roamOffsets[beat.actor].top,
          delay: phase.beatIndex * 380,
        },
      ]);
      setCompletedBeatCount((current) =>
        Math.max(current, phase.beatIndex + 1),
      );
      setPhase({ name: "approach", beatIndex: next });
    }, departDuration);
    return () => window.clearTimeout(id);
  }, [actorHeight, actorWidth, departDuration, phase, reducedMotion, roamOffsets, storyBeats]);

  useEffect(() => {
    if (reducedMotion || phase.name !== "converge") return;
    const id = window.setTimeout(
      completeStory,
      convergeDuration,
    );
    return () => window.clearTimeout(id);
  }, [completeStory, convergeDuration, phase.name, reducedMotion]);

  useEffect(() => {
    if (phase.name === "done") onComplete?.(true);
  }, [onComplete, phase.name]);

  const currentBeat = activeBeatIndex(phase);
  const activeAlly =
    currentBeat == null ? null : storyBeats[currentBeat]?.actor ?? null;
  const activeTarget =
    currentBeat == null
      ? null
      : targets[currentBeat] ??
        fallbackTarget(currentBeat, actorWidth, actorHeight);
  const activeClickTarget = activeTarget
    ? { ...activeTarget, top: activeTarget.top + clickYOffset }
    : null;
  const activeParkedActor = activeAlly
    ? parked.find((actor) => actor.ally === activeAlly) ?? null
    : null;
  const activeParkedPosition = activeAlly
    ? activeParkedActor?.position ??
      parkedPositions[activeAlly] ??
      null
    : null;
  const activePosition =
    currentBeat == null || !activeTarget || !activeAlly
      ? null
      : phase.name === "converge"
        ? phase.startPosition
        : activeParkedPosition ??
          actorEntryPosition(activeTarget, currentBeat, actorWidth, actorHeight);
  const activeRestingTarget =
    currentBeat == null
      ? null
      : restingPosition(currentBeat, actorWidth, actorHeight);

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
  const isStoryFinished = phase.name === "converge" || phase.name === "done";
  const finalTarget =
    storyBeats.length > 0
      ? targets[storyBeats.length - 1] ??
        fallbackTarget(storyBeats.length - 1, actorWidth, actorHeight)
      : null;
  const actorEntries =
    activeAlly == null
      ? parked
      : [
          ...parked.filter((actor) => actor.ally !== activeAlly),
          activeParkedActor ?? {
            id: `story-ally-${activeAlly}`,
            ally: activeAlly,
            position:
              activePosition ??
              actorEntryPosition(
                activeTarget ?? { left: 0, top: 0 },
                currentBeat ?? 0,
                actorWidth,
                actorHeight,
              ),
            roamX: roamOffsets[activeAlly].left,
            roamY: roamOffsets[activeAlly].top,
            delay: (currentBeat ?? 0) * 380,
          },
        ];

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
          isStoryFinished ||
          (beatIndex != null && beatIndex < completedBeatCount);
        const isCurrent = beatIndex === currentBeat;
        const showCurrent =
          isCurrent &&
          (phase.name === "reveal" ||
            phase.name === "hold" ||
            phase.name === "settle");

        let content: ReactNode;
        if (isComplete) {
          content = (
            <span
              style={{
                color: "#121212",
                transition: "color 520ms ease",
              }}
            >
              <SettledLine parts={paragraph.parts} />
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
          left: -actorOffsetLeft,
          top: -actorOffsetTop,
          width: actorWidth,
          height: actorHeight,
          pointerEvents: "none",
          zIndex: 3,
          overflow: "visible",
        }}
      >
        {actorEntries.map((actor) => {
          const isActiveActor = !isConverging && activeAlly === actor.ally;
          const offset = CONVERGENCE_OFFSETS[actor.ally];
          const convergenceTarget = finalTarget
            ? {
                left: finalTarget.left + offset.left,
                top: finalTarget.top + offset.top,
              }
            : actor.position;
          const isFinalBeat = currentBeat === storyBeats.length - 1;
          const isDeparting =
            isActiveActor && phase.name === "settle" && !isFinalBeat;
          const convergenceStart =
            phase.name === "converge" && actor.ally === activeAlly
              ? phase.startPosition
              : null;
          const isFreshActor = isActiveActor && !activeParkedPosition;
          const isRememberedActor =
            isActiveActor && !activeParkedActor && !!activeParkedPosition;
          const activeMotionTarget =
            isDeparting && activeRestingTarget
              ? activeRestingTarget
              : activeClickTarget;
          const target = isConverging
            ? convergenceTarget
            : isActiveActor
              ? activeMotionTarget
              : null;
          const approachStart =
            isActiveActor && phase.name === "approach"
              ? activePosition
              : null;
          const arcPath =
            travelArcs[
              (isActiveActor
                ? currentBeat ?? 0
                : Math.round(actor.delay / 380)) % travelArcs.length
            ];
          const animation = target
            ? {
                x: approachStart
                  ? [approachStart.left, target.left]
                  : convergenceStart
                    ? [convergenceStart.left, target.left]
                    : target.left,
                y: approachStart
                  ? [approachStart.top, target.top]
                  : convergenceStart
                    ? [convergenceStart.top, target.top]
                    : target.top,
                rotate: 0,
                scale: isConverging ? convergenceScale : 1,
              }
            : roamKeyframes(actor, actorWidth, actorHeight);
          const transition = phase.name === "done"
            ? reducedMotion
              ? { duration: 0 }
              : { duration: 0.55, ease: "easeOut" as const }
            : target
            ? travelTransition(
                isConverging
                  ? convergeDuration
                  : isDeparting
                    ? departDuration
                    : approachDuration,
                arcPath,
                reducedMotion,
                // The parked actors still have idle keyframes underneath
                // their travel. Keep the final handoff on Motion's standard
                // tween so it cancels those keyframes and holds the cluster;
                // the arc path remains in use for all story visits.
                !isConverging,
              )
            : reducedMotion
              ? { duration: 0 }
              : {
                  delay: (actor.delay % 1400) / 1000,
                  duration: 7.6 + (actor.delay % 1400) / 1000,
                  ease: "easeInOut" as const,
                  repeat: Infinity,
                  repeatType: "mirror" as const,
                };
          return (
            <motion.div
              key={`${actor.id}-${phase.name === "done" ? "done" : "story"}`}
              data-story-actor={isActiveActor ? "true" : undefined}
              data-story-actor-index={
                isActiveActor ? currentBeat ?? undefined : undefined
              }
              data-story-actor-state={
                isActiveActor ? actorState : undefined
              }
              data-story-parked={isActiveActor ? undefined : actor.id}
              data-story-converged={isConverging ? "true" : undefined}
              data-ally={actor.ally}
              className={`story-ally ${
                isActiveActor ? "story-ally-active" : "story-ally-parked"
              }`}
              initial={
                isFreshActor && activePosition
                  ? {
                      x: activePosition.left,
                      y: activePosition.top,
                      rotate: 0,
                      scale: 1,
                    }
                  : isRememberedActor && activePosition
                    ? {
                        x: activePosition.left,
                        y: activePosition.top,
                        rotate: 0,
                        scale: 1,
                      }
                    : false
              }
              animate={animation}
              transition={transition}
              style={
                {
                  position: "absolute",
                  left: 0,
                  top: 0,
                  width: 60,
                  height: 58,
                  opacity: 1,
                  transformOrigin: isConverging ? "12px 22px" : undefined,
                  willChange: "transform",
                  "--ally-animation-delay": ALLY_ANIMATION_DELAYS[actor.ally],
                } as CSSProperties
              }
            >
              {renderActor(actor.ally, isActiveActor ? actorState : "idle", {
                hideCursor: isConverging,
              })}
            </motion.div>
          );
        })}

        <ClickSpark
          trigger={reducedMotion ? null : spark}
          sparkColor={sparkColor}
        />
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
