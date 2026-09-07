import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
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

const allyPreviewSource = readFileSync(
  fileURLToPath(new URL('./onboarding-ally-preview.tsx', import.meta.url)),
  'utf8',
);
const previewScreenSource = readFileSync(
  fileURLToPath(new URL('./onboarding-preview-screen.tsx', import.meta.url)),
  'utf8',
);
const flowSource = readFileSync(
  fileURLToPath(new URL('./onboarding-flow.tsx', import.meta.url)),
  'utf8',
);
const conversationRouteSource = readFileSync(
  fileURLToPath(new URL('../../app/allies/[allyId]/index.tsx', import.meta.url)),
  'utf8',
);
const conversationLayoutSource = readFileSync(
  fileURLToPath(new URL('../conversation/conversation-layout.tsx', import.meta.url)),
  'utf8',
);
const rootLayoutSource = readFileSync(
  fileURLToPath(new URL('../../app/_layout.tsx', import.meta.url)),
  'utf8',
);

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

  it('uses the existing conversation layout during onboarding', () => {
    expect(previewScreenSource).toContain('<ConversationLayout');
    expect(previewScreenSource).toContain('<ConversationMessage');
    expect(previewScreenSource).toContain('<ConversationThinkingRow');
    expect(previewScreenSource).toContain('headerMode="onboarding"');
    expect(previewScreenSource).toContain('thinking={isThinking}');
    expect(conversationRouteSource).toContain('<ConversationLayout');
    expect(conversationLayoutSource).toContain("headerMode?: 'standard' | 'onboarding'");
    expect(conversationLayoutSource).toContain("if (mode === 'onboarding')");
    expect(conversationLayoutSource).toContain('size={ONBOARDING_PREVIEW_CONVERSATION_ALLY_SIZE}');
    expect(conversationLayoutSource).toContain('getComposerBorderRadius(composerHeight)');
    expect(conversationLayoutSource).toContain('sendButtonMultiline: { alignSelf: \'flex-end\', marginBottom: 6 }');
    expect(conversationLayoutSource).toContain('size={40}');
    expect(conversationLayoutSource).toContain('OnboardingBackButton');
    expect(conversationLayoutSource).toContain('source={require(\'@/assets/allies/icons/send.svg\')}');
    expect(conversationLayoutSource).toContain(
      "const sendColor = useAnimatedColor(headerMode === 'onboarding' ? ally.color : canSend ? ally.color : theme.inactiveButton);",
    );
    expect(conversationLayoutSource).toContain('disabled={!canSend}');
  });

  it('keeps the chat composer attached to the native keyboard animation', () => {
    expect(rootLayoutSource).toContain('<KeyboardProvider>');
    expect(conversationLayoutSource).toContain('<KeyboardChatScrollView');
    expect(conversationLayoutSource).toContain('extraContentPadding={composerExtraPadding}');
    expect(conversationLayoutSource).toContain('offset={insets.bottom}');
    expect(conversationLayoutSource).toContain('<KeyboardStickyView offset={{ closed: 0, opened: insets.bottom }}>');
    expect(conversationLayoutSource).not.toContain('KeyboardAvoidingView');
  });

  it('focuses the composer after the initial Ally greeting finishes', () => {
    expect(previewScreenSource).toContain('onRevealComplete={handleGreetingComplete}');
    expect(previewScreenSource).toContain('focusComposer={greetingFinished}');
    expect(conversationLayoutSource).toContain('focusComposer?: boolean');
    expect(conversationLayoutSource).toContain('composerRef.current?.focus()');
  });

  it('defaults the unselected preview shell color to the theme app background', () => {
    expect(allyPreviewSource).toContain("import { useTheme } from '@/hooks/use-theme';");
    expect(allyPreviewSource).toContain(
      'const animatedShellColor = useAnimatedColor(color ?? theme.appBackground);',
    );
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

  it('keeps preview request status quiet until the request settles', () => {
    expect(flowSource).toContain('useState(initialStep === \'preview\')');
    expect(flowSource).toContain('statusMessage={cloudAttemptBusy ? null : cloudMessage}');
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

  it('forwards the current draft through the supported account continuation path', () => {
    expect(previewScreenSource).toContain('onAccountContinue?: (draft: string) => void | Promise<void>;');
    expect(previewScreenSource.match(/void onAccountContinue\(draft\);/g)).toHaveLength(2);
    expect(previewScreenSource).not.toContain('Continue with ChatGPT');
    expect(previewScreenSource).toContain("const TERMS_URL = 'https://yourallies.io/terms';");
    expect(previewScreenSource).toContain("const PRIVACY_URL = 'https://yourallies.io/privacy';");
    expect(previewScreenSource).toContain('WebBrowser.openBrowserAsync(url)');
  });

  it('saves the pending Ally command before starting native Google sign-in', () => {
    const accountContinueSource = flowSource.slice(
      flowSource.indexOf('  const handleAccountContinue'),
      flowSource.indexOf('  const handleBasicsComplete'),
    );

    expect(flowSource).not.toContain("import { useGoogleSignIn } from '@/features/auth/use-google-sign-in';");
    expect(accountContinueSource).toContain('if (!cloudAttempt || cloudAttempt.inputKey !== cloudInputKey)');
    expect(accountContinueSource).toContain('await pendingCommandStore.saveCreate(command);');
    expect(accountContinueSource).toContain("router.replace('/sign-in?returnTo=/allies/new/complete' as never);");
    expect(accountContinueSource).toContain("await session.startGoogleSignIn('/allies/new/complete');");
    expect(accountContinueSource.indexOf('await pendingCommandStore.saveCreate(command);')).toBeLessThan(
      accountContinueSource.indexOf("await session.startGoogleSignIn('/allies/new/complete');")
    );
    expect(accountContinueSource).not.toContain('isGoogleSignInAvailable');
    expect(accountContinueSource).not.toContain('setCloudSubmitting');
    expect(accountContinueSource).not.toContain("router.replace('/?returnTo=%2Fallies%2Fnew%2Fcomplete' as never);");
    expect(accountContinueSource).toContain(
      "}, [cloudAttempt, cloudInputKey, flow, pendingCreate, router, session]);",
    );
    expect(flowSource).toContain('idempotencyKey: Crypto.randomUUID(),');
    expect(flowSource).not.toContain('mock.registerAlly');
    expect(flowSource).not.toContain('mock.sendMessage');
    expect(conversationRouteSource).toContain('useAlly');
  });

  it('returns the visible conversation back button to the Allies home', () => {
    expect(conversationRouteSource).toContain("onBack={() => router.replace('/allies' as never)}");
    expect(conversationRouteSource).not.toContain('router.back()');
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
