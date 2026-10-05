"use client";

import { createContext, createElement, useContext, useMemo, useReducer, type ReactNode } from "react";
import { ALLY_SHAPES, type AllyShape } from "../../../components/ally-avatar";

export const ALLY_COLORS = [
  "#ff5800",
  "#fd304f",
  "#0d92fd",
  "#be9bf5",
  "#3446e9",
  "#a3f06f",
  "#fbe65f",
] as const;

export { ALLY_SHAPES };

export const PERSONALITIES = ["Concise", "Quirky", "Analytical", "Funny"] as const;

export const JOB_SUGGESTIONS = [
  "Teach me a language",
  "Track my finances",
  "Manage my calendar",
] as const;

export const NAME_LIMIT = 80;
export const JOB_LIMIT = 200;

export type OnboardingStep =
  | "intro"
  | "welcome"
  | "name"
  | "look"
  | "job"
  | "personality"
  | "preview";

type OnboardingState = {
  step: OnboardingStep;
  hasIntroduction: boolean;
  hasSeenJobNudge: boolean;
  name: string;
  shape: AllyShape;
  hasSwipedAvatar: boolean;
  color: string | null;
  job: string;
  personalities: string[];
  personalityNote: string;
  personalityRaw: string | null;
};

type OnboardingActions = {
  markJobNudgeSeen: () => void;
  setName: (name: string) => void;
  setShape: (shape: AllyShape) => void;
  markSwiped: () => void;
  setColor: (color: string) => void;
  setJob: (job: string) => void;
  togglePersonality: (trait: string) => void;
  setPersonalityNote: (note: string) => void;
  hydrate: (input: {
    name: string;
    shape: AllyShape;
    color: string | null;
    job: string;
    personalities: string[];
    personalityNote: string;
    personalityRaw: string | null;
  }) => void;
  goTo: (step: OnboardingStep) => void;
  back: () => void;
};

type OnboardingStore = OnboardingState & OnboardingActions;

type OnboardingAction =
  | { type: "markJobNudgeSeen" }
  | { type: "setName"; name: string }
  | { type: "setShape"; shape: AllyShape }
  | { type: "markSwiped" }
  | { type: "setColor"; color: string }
  | { type: "setJob"; job: string }
  | { type: "togglePersonality"; trait: string }
  | { type: "setPersonalityNote"; note: string }
  | { type: "hydrate"; input: Parameters<OnboardingActions["hydrate"]>[0] }
  | { type: "goTo"; step: OnboardingStep }
  | { type: "back" };

const BACK: Record<OnboardingStep, OnboardingStep | null> = {
  welcome: null,
  intro: "welcome",
  job: "intro",
  name: "job",
  look: "name",
  personality: "look",
  preview: "personality",
};

const INITIAL_STATE: OnboardingState = {
  step: "welcome",
  hasIntroduction: true,
  hasSeenJobNudge: false,
  name: "",
  shape: "ghosty",
  hasSwipedAvatar: false,
  color: null,
  job: "",
  personalities: [],
  personalityNote: "",
  personalityRaw: null,
};

function personalityPrompt(trait: string) {
  return `Be ${trait.toLocaleLowerCase()}, `;
}

function reduceOnboardingState(state: OnboardingState, action: OnboardingAction): OnboardingState {
  switch (action.type) {
    case "markJobNudgeSeen":
      return { ...state, hasSeenJobNudge: true };
    case "setName":
      return { ...state, name: action.name.slice(0, NAME_LIMIT) };
    case "setShape":
      return { ...state, shape: action.shape };
    case "markSwiped":
      return { ...state, hasSwipedAvatar: true };
    case "setColor":
      return { ...state, color: action.color };
    case "setJob":
      return { ...state, job: action.job.slice(0, JOB_LIMIT) };
    case "togglePersonality": {
      const selected = state.personalities.includes(action.trait);
      const prompt = personalityPrompt(action.trait);
      return {
        ...state,
        personalityRaw: null,
        personalities: selected
          ? state.personalities.filter((item) => item !== action.trait)
          : [...state.personalities, action.trait],
        personalityNote: selected
          ? state.personalityNote.replace(prompt, "")
          : `${state.personalityNote}${prompt}`.slice(0, JOB_LIMIT),
      };
    }
    case "setPersonalityNote":
      return {
        ...state,
        personalityNote: action.note.slice(0, JOB_LIMIT),
        personalityRaw: null,
      };
    case "hydrate":
      return {
        ...state,
        name: action.input.name,
        shape: action.input.shape,
        hasSwipedAvatar: action.input.color !== null,
        color: action.input.color,
        job: action.input.job,
        personalities: action.input.personalities,
        personalityNote: action.input.personalityNote,
        personalityRaw: action.input.personalityRaw,
      };
    case "goTo":
      return { ...state, step: action.step };
    case "back": {
      const previous = BACK[state.step];
      return previous ? { ...state, step: previous } : state;
    }
  }
}

const OnboardingStoreContext = createContext<OnboardingStore | null>(null);

export function OnboardingStateProvider({
  children,
  initialStep = "welcome",
}: {
  children: ReactNode;
  initialStep?: OnboardingStep;
}) {
  const [state, dispatch] = useReducer(
    reduceOnboardingState,
    initialStep,
    (step): OnboardingState => ({ ...INITIAL_STATE, step, hasIntroduction: step === "welcome" || step === "intro" }),
  );
  const actions = useMemo<OnboardingActions>(
    () => ({
      markJobNudgeSeen: () => dispatch({ type: "markJobNudgeSeen" }),
      setName: (name) => dispatch({ type: "setName", name }),
      setShape: (shape) => dispatch({ type: "setShape", shape }),
      markSwiped: () => dispatch({ type: "markSwiped" }),
      setColor: (color) => dispatch({ type: "setColor", color }),
      setJob: (job) => dispatch({ type: "setJob", job }),
      togglePersonality: (trait) => dispatch({ type: "togglePersonality", trait }),
      setPersonalityNote: (note) => dispatch({ type: "setPersonalityNote", note }),
      hydrate: (input) => dispatch({ type: "hydrate", input }),
      goTo: (step) => dispatch({ type: "goTo", step }),
      back: () => dispatch({ type: "back" }),
    }),
    [],
  );
  const store = useMemo<OnboardingStore>(
    () => ({ ...state, ...actions }),
    [actions, state],
  );

  return createElement(OnboardingStoreContext.Provider, { value: store }, children);
}

export function useOnboardingStore<T>(selector: (state: OnboardingStore) => T): T {
  const store = useContext(OnboardingStoreContext);
  if (!store) throw new Error("useOnboardingStore must be used within OnboardingStateProvider");
  return selector(store);
}
