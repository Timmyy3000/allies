
import { describe, expect, it } from 'vitest';

import {
  ONBOARDING_PREVIEW_COMPOSER_INITIAL_BORDER_RADIUS,
  ONBOARDING_PREVIEW_COMPOSER_TEXT_STYLE,
  ONBOARDING_PREVIEW_ENTRANCE_DELAY_MS,
  ONBOARDING_PREVIEW_GREETING_CHAR_INTERVAL_MS,
  ONBOARDING_PREVIEW_GREETING_REVEAL_DURATION_MS,
  ONBOARDING_PREVIEW_HEADER_NAME_GAP,
  ONBOARDING_PREVIEW_HEADER_NAME_TEXT_STYLE,
  ONBOARDING_PREVIEW_NAME_CHAR_INTERVAL_MS,
  ONBOARDING_PREVIEW_CONVERSATION_ALLY_SIZE,
  ONBOARDING_PREVIEW_GREETING_TOP_GAP,
  ONBOARDING_PREVIEW_FOCUS_DURATION_MS,
  ONBOARDING_PREVIEW_THINKING_SHINE_DURATION_MS,
  ONBOARDING_PREVIEW_BODY_TEXT_BOLD_STYLE,
  ONBOARDING_PREVIEW_BODY_TEXT_STYLE,
  getAccountPromptOpenMode,
  getOnboardingFocusDelayMs,
  getOnboardingGreetingBlocks,
  getOnboardingGreetingRuns,
  getOnboardingGreetingRevealStep,
  getOnboardingReplyAction,
  getNextOnboardingPreviewPhase,
  getOnboardingGreeting,
  getRosterPreview,
  getVisibleOnboardingGreeting,
} from './onboarding-preview';
import { ONBOARDING_POST_SETUP_DURATION_MS } from './onboarding-motion';

describe('onboarding preview flow', () => {
  it('keeps the handoff timing short and deliberate', () => {
    expect(ONBOARDING_PREVIEW_ENTRANCE_DELAY_MS).toBe(2400);
    expect(ONBOARDING_PREVIEW_GREETING_CHAR_INTERVAL_MS).toBe(12);
    expect(ONBOARDING_PREVIEW_GREETING_REVEAL_DURATION_MS).toBe(2400);
    expect(ONBOARDING_PREVIEW_NAME_CHAR_INTERVAL_MS).toBe(55);
    expect(ONBOARDING_PREVIEW_THINKING_SHINE_DURATION_MS).toBe(1700);
    expect(ONBOARDING_PREVIEW_FOCUS_DURATION_MS).toBe(280);
    expect(getOnboardingFocusDelayMs(0, 0)).toBe(0);
    expect(getOnboardingFocusDelayMs(8, 0)).toBe(35);
    expect(getOnboardingFocusDelayMs(9, 4)).toBe(25);
  });

  it('keeps the conversation preview aligned with onboarding typography and spacing', () => {
    expect(ONBOARDING_PREVIEW_COMPOSER_INITIAL_BORDER_RADIUS).toBe(100);
    expect(ONBOARDING_PREVIEW_CONVERSATION_ALLY_SIZE).toBe(40.32);
    expect(ONBOARDING_PREVIEW_HEADER_NAME_GAP).toBe(12);
    expect(ONBOARDING_PREVIEW_GREETING_TOP_GAP).toBe(18);
    expect(ONBOARDING_PREVIEW_HEADER_NAME_TEXT_STYLE).toEqual({
      fontFamily: 'OpenRundeSemibold',
      fontSize: 18,
      includeFontPadding: true,
      letterSpacing: -1,
      lineHeight: 24,
    });
    expect(ONBOARDING_PREVIEW_BODY_TEXT_STYLE).toEqual({
      fontFamily: 'OpenRundeMedium',
      fontSize: 16,
      letterSpacing: -0.5,
      lineHeight: 22,
    });
    expect(ONBOARDING_PREVIEW_BODY_TEXT_BOLD_STYLE).toEqual({
      fontFamily: 'OpenRundeSemibold',
      fontSize: 16,
      letterSpacing: -0.5,
      lineHeight: 22,
    });
    expect(ONBOARDING_PREVIEW_COMPOSER_TEXT_STYLE).toEqual({
      fontFamily: 'OpenRundeMedium',
      fontSize: 16,
      letterSpacing: -0.5,
      lineHeight: 16,
    });
  });

  it('keeps bold greeting labels bold while the message types in', () => {
    const fullGreeting = getOnboardingGreeting('Sally Morano');
    const greeting = getOnboardingGreetingRuns(fullGreeting, fullGreeting.length);

    expect(greeting).toContainEqual({ bold: true, text: '🌟 What We Can Do Together' });
    expect(greeting).toContainEqual({ bold: true, text: 'Chat Freely:' });
    expect(greeting).toContainEqual({ bold: true, text: 'Brainstorm Ideas:' });
    expect(greeting.some((run) => !run.bold && run.text.includes('Welcome! I am your ally'))).toBe(
      true,
    );
  });

  it('keeps the greeting heading and bullets as separate layout blocks', () => {
    const blocks = getOnboardingGreetingBlocks(getOnboardingGreeting('Sally Morano'));

    expect(blocks.map(({ type }) => type)).toEqual([
      'paragraph',
      'paragraph',
      'heading',
      'bullet',
      'bullet',
    ]);
    expect(blocks[2]).toMatchObject({
      heading: 'What We Can Do Together',
      type: 'heading',
    });
    expect(blocks[3]).toMatchObject({
      body: 'Ask me questions about history, science, pop culture, or everyday facts.',
      label: 'Chat Freely:',
      type: 'bullet',
    });
    expect(blocks[4]).toMatchObject({
      body: 'Outline your next big business project, travel itinerary, or workout plan.',
      label: 'Brainstorm Ideas:',
      type: 'bullet',
    });
  });

  it('advances through coming alive, thinking, and ready in order', () => {
    expect(getNextOnboardingPreviewPhase('coming-alive')).toBe('thinking');
    expect(getNextOnboardingPreviewPhase('thinking')).toBe('thinking');
    expect(getNextOnboardingPreviewPhase('thinking', true)).toBe('ready');
    expect(getNextOnboardingPreviewPhase('ready')).toBe('ready');
  });

  it('keeps the post-setup confirmation visible for two seconds', () => {
    expect(ONBOARDING_POST_SETUP_DURATION_MS).toBe(2000);
  });

  it('prompts for an account before the first reply is submitted', () => {
    expect(getOnboardingReplyAction(true, true)).toBe('prompt-account');
    expect(getOnboardingReplyAction(true, false)).toBe('submit');
    expect(getOnboardingReplyAction(false, true)).toBe('ignore');
  });

  it('waits for the keyboard to finish dismissing before opening the account prompt', () => {
    expect(getAccountPromptOpenMode(true)).toBe('after-keyboard-hide');
    expect(getAccountPromptOpenMode(false)).toBe('immediate');
  });

  it('builds the first Ally greeting and reveals it incrementally', () => {
    const greeting = getOnboardingGreeting('Sally Morano');

    expect(greeting).toContain('Welcome! I am your ally');
    expect(greeting).toContain('🌟 What We Can Do Together');
    expect(greeting).toContain('• Chat Freely:');
    expect(getVisibleOnboardingGreeting(greeting, 7)).toBe(greeting.slice(0, 7));
    expect(getVisibleOnboardingGreeting(greeting, -1)).toBe('');
    expect(getVisibleOnboardingGreeting(greeting, greeting.length + 10)).toBe(greeting);
  });

  it('keeps the greeting reveal under the short animation budget', () => {
    const greetingLength = getOnboardingGreeting('Sally Morano').length;
    const revealStep = getOnboardingGreetingRevealStep(greetingLength);
    const revealTicks = Math.ceil(greetingLength / revealStep);

    expect(revealStep).toBeGreaterThan(1);
    expect(revealTicks * ONBOARDING_PREVIEW_GREETING_CHAR_INTERVAL_MS).toBeLessThanOrEqual(
      ONBOARDING_PREVIEW_GREETING_REVEAL_DURATION_MS,
    );
    expect(getOnboardingGreetingRevealStep(0)).toBe(1);
  });

  it('bounds the roster preview without leaving layout-breaking whitespace', () => {
    expect(getRosterPreview('  Welcome!\n\nI am your Ally.  ')).toBe('Welcome! I am your Ally.');
    expect(getRosterPreview('A message that is longer than the roster row allows.', 24)).toBe(
      'A message that is longe…',
    );
    expect(getRosterPreview('')).toBe('Welcome to your Ally');
  });
});
