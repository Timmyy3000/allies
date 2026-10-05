export type OnboardingPreviewPhase = 'coming-alive' | 'thinking' | 'ready';

export const ONBOARDING_PREVIEW_ENTRANCE_DELAY_MS = 2400;
export const ONBOARDING_PREVIEW_GREETING_CHAR_INTERVAL_MS = 12;
export const ONBOARDING_PREVIEW_GREETING_REVEAL_DURATION_MS = 2400;
export const ONBOARDING_PREVIEW_NAME_CHAR_INTERVAL_MS = 55;
export const ONBOARDING_PREVIEW_THINKING_SHINE_DURATION_MS = 1700;
export const ONBOARDING_PREVIEW_FOCUS_DURATION_MS = 280;
export const ONBOARDING_PREVIEW_HEADER_AVATAR_SIZE = 24;
export const ONBOARDING_PREVIEW_THINKING_AVATAR_SIZE = 28;
export const ONBOARDING_PREVIEW_CONVERSATION_ALLY_SIZE = ONBOARDING_PREVIEW_THINKING_AVATAR_SIZE * 1.44;
export const ONBOARDING_PREVIEW_HEADER_NAME_GAP = 12;
export const ONBOARDING_PREVIEW_HEADER_NAME_TEXT_STYLE = {
  fontFamily: 'OpenRundeSemibold',
  fontSize: 18,
  includeFontPadding: true,
  letterSpacing: -1,
  lineHeight: 24,
} as const;
export const ONBOARDING_PREVIEW_GREETING_TOP_GAP = 18;
export const ONBOARDING_PREVIEW_BODY_TEXT_STYLE = {
  fontFamily: 'OpenRundeMedium',
  fontSize: 16,
  letterSpacing: -0.5,
  lineHeight: 22,
} as const;
export const ONBOARDING_PREVIEW_BODY_TEXT_BOLD_STYLE = {
  fontFamily: 'OpenRundeSemibold',
  fontSize: 16,
  letterSpacing: -0.5,
  lineHeight: 22,
} as const;
export const ONBOARDING_PREVIEW_COMPOSER_TEXT_STYLE = {
  fontFamily: 'OpenRundeMedium',
  fontSize: 16,
  letterSpacing: -0.5,
  lineHeight: 16,
} as const;
export const ONBOARDING_PREVIEW_COMPOSER_INITIAL_BORDER_RADIUS = 100;

export function getOnboardingFocusDelayMs(index: number, start: number): number {
  return Math.min(35, Math.max(0, index - start) * 5);
}

export function getOnboardingGreetingRevealStep(greetingLength: number): number {
  const revealTicks = Math.max(
    1,
    Math.floor(
      ONBOARDING_PREVIEW_GREETING_REVEAL_DURATION_MS /
        ONBOARDING_PREVIEW_GREETING_CHAR_INTERVAL_MS,
    ),
  );

  return Math.max(1, Math.ceil(Math.max(0, greetingLength) / revealTicks));
}

export type OnboardingGreetingRun = {
  bold: boolean;
  text: string;
};

export type OnboardingGreetingBlock =
  | {
      heading: string;
      start: number;
      textStart: number;
      type: 'heading';
    }
  | {
      body: string;
      bodyStart: number;
      label: string;
      labelStart: number;
      markerStart: number;
      type: 'bullet';
    }
  | {
      start: number;
      text: string;
      type: 'paragraph';
    };

export function getOnboardingGreetingBlocks(greeting: string): OnboardingGreetingBlock[] {
  const blocks: OnboardingGreetingBlock[] = [];
  let blockStart = 0;

  greeting.split('\n\n').forEach((rawBlock, blockIndex, rawBlocks) => {
    if (rawBlock.startsWith('🌟 ')) {
      blocks.push({
        heading: rawBlock.slice('🌟 '.length),
        start: blockStart,
        textStart: blockStart,
        type: 'heading',
      });
    } else if (rawBlock.startsWith('• ')) {
      const labelEnd = rawBlock.indexOf(': ', 2);

      if (labelEnd > 2) {
        blocks.push({
          body: rawBlock.slice(labelEnd + 2),
          bodyStart: blockStart + labelEnd + 2,
          label: rawBlock.slice(2, labelEnd + 1),
          labelStart: blockStart + 2,
          markerStart: blockStart,
          type: 'bullet',
        });
      } else {
        blocks.push({
          start: blockStart,
          text: rawBlock,
          type: 'paragraph',
        });
      }
    } else {
      blocks.push({
        start: blockStart,
        text: rawBlock,
        type: 'paragraph',
      });
    }

    blockStart += rawBlock.length;
    if (blockIndex < rawBlocks.length - 1) blockStart += 2;
  });

  return blocks;
}

export function getOnboardingGreetingRuns(
  greeting: string,
  characterCount: number,
): OnboardingGreetingRun[] {
  const visibleLength = Math.min(Math.max(0, characterCount), greeting.length);
  if (visibleLength === 0) return [];

  const boldMarkers = [
    '🌟 What We Can Do Together',
    'Chat Freely:',
    'Brainstorm Ideas:',
  ];
  const boldRanges = boldMarkers
    .map((marker) => {
      const start = greeting.indexOf(marker);
      return start === -1 ? null : { end: start + marker.length, start };
    })
    .filter((range): range is { end: number; start: number } => range !== null)
    .sort((first, second) => first.start - second.start);

  const runs: OnboardingGreetingRun[] = [];
  let cursor = 0;

  for (const range of boldRanges) {
    if (range.start >= visibleLength) break;

    if (cursor < range.start) {
      runs.push({
        bold: false,
        text: greeting.slice(cursor, Math.min(range.start, visibleLength)),
      });
    }

    const boldEnd = Math.min(range.end, visibleLength);
    if (boldEnd > range.start) {
      runs.push({
        bold: true,
        text: greeting.slice(range.start, boldEnd),
      });
    }

    cursor = range.end;
  }

  if (cursor < visibleLength) {
    runs.push({
      bold: false,
      text: greeting.slice(cursor, visibleLength),
    });
  }

  return runs;
}

const FIRST_ALLY_GREETING = [
  'Welcome! I am your ally, and I am thrilled to help you make your day easier, more productive, and fun. Think of me as your always-available partner for brainstorming, writing, learning, and organising.',
  'No task is too big or too small, and I am constantly learning new ways to assist you better. Let us collaborate and build something great together.',
  '🌟 What We Can Do Together',
  '• Chat Freely: Ask me questions about history, science, pop culture, or everyday facts.',
  '• Brainstorm Ideas: Outline your next big business project, travel itinerary, or workout plan.',
].join('\n\n');

export function getNextOnboardingPreviewPhase(
  phase: OnboardingPreviewPhase,
  responseReady = false,
): OnboardingPreviewPhase {
  if (phase === 'coming-alive') return 'thinking';
  if (phase === 'thinking' && responseReady) return 'ready';
  return phase;
}

export type OnboardingReplyAction = 'ignore' | 'prompt-account' | 'submit';

export function getAccountPromptOpenMode(keyboardVisible: boolean): 'after-keyboard-hide' | 'immediate' {
  return keyboardVisible ? 'after-keyboard-hide' : 'immediate';
}

export function getOnboardingReplyAction(
  canSend: boolean,
  requiresAccount: boolean,
): OnboardingReplyAction {
  if (!canSend) return 'ignore';
  return requiresAccount ? 'prompt-account' : 'submit';
}

export function getOnboardingGreeting(_allyName: string): string {
  return FIRST_ALLY_GREETING;
}

export function getVisibleOnboardingGreeting(
  greeting: string,
  characterCount: number,
): string {
  return greeting.slice(0, Math.max(0, characterCount));
}

export function getRosterPreview(greeting: string, maximumLength = 44): string {
  const normalized = greeting.replace(/\s+/gu, ' ').trim();
  if (!normalized) return 'Welcome to your Ally';
  if (normalized.length <= maximumLength) return normalized;

  return `${normalized.slice(0, Math.max(1, maximumLength - 1)).trimEnd()}…`;
}
