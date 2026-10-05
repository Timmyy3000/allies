import { Image } from 'expo-image';
import * as Crypto from 'expo-crypto';
import { useRouter } from 'expo-router';
import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { BackHandler, Keyboard, StyleSheet } from 'react-native';

import { isCloudError, type AllyViewModel } from '@allies/cloud-client';

import { PrimaryButton } from '@/components/ui/primary-button';
import { allyKeys } from '@/features/allies/queries';
import { pendingCommandStore, toCloudCreateAllyInput, type PendingCreateCommand } from '@/lib/pending-command-store';
import { useNativeSession } from '@/lib/session/session-context';
import { requestNotificationPermission } from '@/lib/notifications/notification-permission';

import OnboardingScreen from './onboarding-screen';
import { AllyNameScreen } from './ally-name-screen';
import { OnboardingJobScreen } from './onboarding-job-screen';
import { OnboardingLookScreen } from './onboarding-look-screen';
import { OnboardingPersonalityScreen } from './onboarding-personality-screen';
import { OnboardingAllyPreview } from './onboarding-ally-preview';
import { OnboardingPreviewScreen } from './onboarding-preview-screen';
import {
  OnboardingBasicsScreen,
  OnboardingNotificationsScreen,
} from './onboarding-post-setup';
import {
  getOnboardingChrome,
  getOnboardingHeaderAllyVariant,
  isOnboardingFooterDisabled,
  OnboardingShell,
} from './onboarding-shell';
import { ONBOARDING_HEADER_ALLY_ARTWORK_SCALE } from './onboarding-layout';
import {
  INITIAL_ONBOARDING_FLOW,
  getNextOnboardingStep,
  getOnboardingAccent,
  getPersonalityNoteForSelection,
  getPreviousOnboardingStep,
  isAllyNameReady,
  isJobDescriptionReady,
  isLookReady,
  isPersonalityReady,
  MAX_JOB_DESCRIPTION_LENGTH,
  MAX_NAME_LENGTH,
  MAX_PERSONALITY_NOTE_LENGTH,
  isAllyColor,
  ALLY_SHAPES,
  type Personality,
  type OnboardingFlowState,
  type OnboardingStep,
} from './onboarding-state';
import { toCreateAllyInput, toOnboardingAttemptInput } from './onboarding-cloud-input';

const PENDING_CREATE_LIFETIME_MS = 7 * 24 * 60 * 60 * 1000;

function waitForKeyboardToHide() {
  if (!Keyboard.isVisible()) return Promise.resolve();

  return new Promise<void>((resolve) => {
    const subscription = Keyboard.addListener('keyboardDidHide', () => {
      subscription.remove();
      resolve();
    });
    Keyboard.dismiss();
  });
}

function isTransientCloudError(error: unknown): boolean {
  return isCloudError(error) && ['network', 'timeout', 'server', 'throttled'].includes(error.kind);
}

function isInvalidOnboardingAttempt(error: unknown): boolean {
  return isCloudError(error) && ['bad-request', 'not-found', 'validation'].includes(error.kind);
}

function createCommand(
  flow: OnboardingFlowState,
  attemptToken: string,
  reply: string,
): PendingCreateCommand {
  const createdAt = Date.now();
  const input = toCreateAllyInput(flow, attemptToken, reply);
  return {
    kind: 'create',
    name: input.name,
    job: input.job,
    personality: input.personality,
    appearance: {
      catalogVersion: input.appearanceCatalogVersion,
      key: input.appearanceKey,
    },
    onboardingAttempt: input.onboardingAttempt,
    reply: input.reply,
    idempotencyKey: Crypto.randomUUID(),
    createdAt: new Date(createdAt).toISOString(),
    expiresAt: new Date(createdAt + PENDING_CREATE_LIFETIME_MS).toISOString(),
  };
}

function commandMatches(
  command: PendingCreateCommand,
  flow: OnboardingFlowState,
  attemptToken: string,
  reply: string,
): boolean {
  return command.onboardingAttempt === attemptToken
    && command.reply === reply
    && commandMatchesConfig(command, flow);
}

function commandMatchesConfig(command: PendingCreateCommand, flow: OnboardingFlowState): boolean {
  const input = toOnboardingAttemptInput(flow);
  return command.name === input.name
    && command.job === input.job
    && command.personality === input.personality
    && command.appearance.catalogVersion === input.appearanceCatalogVersion
    && command.appearance.key === input.appearanceKey;
}

function messageForCreateError(error: unknown): string {
  if (isCloudError(error) && error.kind === 'forbidden') return 'This Ally could not be created in the current workspace.';
  if (isCloudError(error) && error.kind === 'unauthorized') return 'Your sign-in expired. Sign in again to finish creating your Ally.';
  return 'We could not create your Ally. Try again.';
}

type OnboardingFlowProps = {
  initialStep?: OnboardingStep;
  onExit?: () => void;
};

export default function OnboardingFlow({
  initialStep = 'welcome',
  onExit,
}: OnboardingFlowProps) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const session = useNativeSession();
  const [flow, setFlow] = useState<OnboardingFlowState>(() => ({
    ...INITIAL_ONBOARDING_FLOW,
    step: initialStep,
  }));
  const [helpOpen, setHelpOpen] = useState(false);
  const [cloudAttempt, setCloudAttempt] = useState<{ inputKey: string; attemptToken: string; greeting: string } | null>(null);
  const [cloudAttemptBusy, setCloudAttemptBusy] = useState(initialStep === 'preview');
  const [cloudAttemptRequest, setCloudAttemptRequest] = useState(0);
  const [cloudMessage, setCloudMessage] = useState<string | null>(null);
  const [cloudSubmitting, setCloudSubmitting] = useState(false);
  const [retryPending, setRetryPending] = useState(false);
  const [pendingCreate, setPendingCreate] = useState<PendingCreateCommand | null>(null);
  const [createdAlly, setCreatedAlly] = useState<AllyViewModel | null>(null);
  const mountedRef = useRef(true);
  const createOperationRef = useRef(0);
  const activeCreateControllerRef = useRef<AbortController | null>(null);
  const sessionIdentityRef = useRef<string | null>(null);
  const sessionIdentityInitializedRef = useRef(false);
  const cloudInput = useMemo(() => toOnboardingAttemptInput(flow), [flow]);
  const cloudInputKey = JSON.stringify(cloudInput);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      createOperationRef.current += 1;
      activeCreateControllerRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    const nextIdentity = session.status === 'signed-in' && session.account
      ? `${session.account.userId}:${session.account.workspace.id}`
      : null;
    if (sessionIdentityInitializedRef.current && sessionIdentityRef.current !== nextIdentity) {
      createOperationRef.current += 1;
      activeCreateControllerRef.current?.abort();
    }
    sessionIdentityRef.current = nextIdentity;
    sessionIdentityInitializedRef.current = true;
  }, [session.account, session.status]);

  useEffect(() => {
    if (flow.step !== 'welcome' && flow.step !== 'name') return;
    if (session.status !== 'signed-in' || !session.account) return;

    let active = true;
    const capturedIdentity = sessionIdentityRef.current;
    const isCurrent = () => active
      && mountedRef.current
      && sessionIdentityRef.current === capturedIdentity;
    void pendingCommandStore.readCreate(session.account.userId, session.account.workspace.id)
      .then((command) => {
        if (!isCurrent() || !command) return;
        const colorValue = command.appearance.key.split(':')[1];
        const color = colorValue ? `#${colorValue.toUpperCase()}` : '';
        const shape = command.appearance.key.split(':')[0];
        if (!(ALLY_SHAPES as readonly string[]).includes(shape) || !isAllyColor(color)) return;
        setPendingCreate(command);
        setCloudAttempt(null);
        setCloudAttemptBusy(true);
        setFlow({
          allyName: command.name,
          allyShape: shape as OnboardingFlowState['allyShape'],
          hasSwipedAvatar: true,
          jobDescription: command.job,
          personalityNote: command.personality,
          personalities: [],
          selectedColor: color,
          step: 'preview',
        });
        setCloudMessage('Review the saved reply before you continue.');
      })
      .catch(() => {
        if (isCurrent()) setCloudMessage('We could not restore the saved Ally creation. Try again.');
      });

    return () => {
      active = false;
    };
  }, [flow.step, session.account, session.status]);

  useEffect(() => {
    if (flow.step !== 'preview') return undefined;

    const controller = new AbortController();
    void (async () => {
      try {
        if (!session.accountClient) {
          setCloudMessage('Cloud is not configured for this build. Set EXPO_PUBLIC_CLOUD_API_URL and restart Expo.');
          return;
        }
        const attempt = await session.accountClient.beginOnboarding(cloudInput, controller.signal);
        if (controller.signal.aborted) return;
        setCloudAttempt({ inputKey: cloudInputKey, ...attempt });
        setCloudMessage(null);
      } catch {
        if (!controller.signal.aborted) setCloudMessage('We could not prepare the Cloud preview. Try again.');
      } finally {
        if (!controller.signal.aborted) setCloudAttemptBusy(false);
      }
    })();

    return () => controller.abort();
  }, [cloudAttemptRequest, cloudInput, cloudInputKey, flow.allyName, flow.jobDescription, flow.step, session.accountClient]);

  const handleCloudReply = useCallback(async (reply: string): Promise<boolean> => {
    if (!cloudAttempt || cloudAttempt.inputKey !== cloudInputKey) {
      setCloudMessage('The preview expired. We are preparing a new one. Review your reply and send it again.');
      setCloudAttempt(null);
      setCloudAttemptBusy(true);
      setCloudAttemptRequest((current) => current + 1);
      return false;
    }

    activeCreateControllerRef.current?.abort();
    const controller = new AbortController();
    activeCreateControllerRef.current = controller;
    const operation = ++createOperationRef.current;
    const capturedIdentity = sessionIdentityRef.current;
    const isCurrent = () => mountedRef.current
      && operation === createOperationRef.current
      && !controller.signal.aborted
      && sessionIdentityRef.current === capturedIdentity;

    try {
      let command = pendingCreate;
      if (command && !commandMatches(command, flow, cloudAttempt.attemptToken, reply)) {
        if (command.reply === reply && commandMatchesConfig(command, flow)) {
          command = { ...command, onboardingAttempt: cloudAttempt.attemptToken };
          await pendingCommandStore.saveCreate(command);
          if (!isCurrent()) return false;
          setPendingCreate(command);
        } else {
          setCloudMessage('Retry the saved reply before starting another Ally.');
          setRetryPending(true);
          return false;
        }
      }

      if (!command) {
        const persisted = await pendingCommandStore.readCreate(
          session.status === 'signed-in' && session.account ? session.account.userId : undefined,
          session.status === 'signed-in' && session.account ? session.account.workspace.id : undefined,
        );
        if (persisted) {
          if (!commandMatches(persisted, flow, cloudAttempt.attemptToken, reply)) {
            if (persisted.reply === reply && commandMatchesConfig(persisted, flow)) {
              command = { ...persisted, onboardingAttempt: cloudAttempt.attemptToken };
              await pendingCommandStore.saveCreate(command);
              if (!isCurrent()) return false;
              setPendingCreate(command);
            } else {
              setCloudMessage('A saved Ally creation needs to finish before starting another one.');
              setRetryPending(true);
              setPendingCreate(persisted);
              return false;
            }
          } else {
            command = persisted;
          }
        } else {
          command = createCommand(flow, cloudAttempt.attemptToken, reply);
          await pendingCommandStore.saveCreate(command);
          if (!isCurrent()) return false;
        }
        setPendingCreate(command);
      }

      if (!isCurrent()) return false;
      if (session.status !== 'signed-in' || !session.account || !session.accountClient || !session.adapter) {
        setRetryPending(true);
        setCloudMessage('Sign in to finish creating your Ally.');
        return false;
      }

      setCloudSubmitting(true);
      const boundCommand = await pendingCommandStore.bindCreate(
        session.account.userId,
        session.account.workspace.id,
      );
      if (!isCurrent()) return false;
      if (!boundCommand) {
        setPendingCreate(null);
        setRetryPending(false);
        setCloudMessage('Your saved Ally creation no longer belongs to this session. Start again.');
        return false;
      }

      const ally = await session.adapter.withRefresh(() => session.accountClient!.createAlly(
        session.account!.workspace.id,
        toCloudCreateAllyInput(boundCommand),
        boundCommand.idempotencyKey,
        controller.signal,
      ));
      if (!isCurrent()) return false;
      try {
        await pendingCommandStore.deleteCreate();
      } catch {
        // Cloud accepted the idempotent command; a later retry can reconcile local cleanup.
      }
      if (!isCurrent()) return false;
      const workspaceId = session.account.workspace.id;
      queryClient.setQueryData(allyKeys.detail(workspaceId, ally.id), ally);
      void queryClient.invalidateQueries({ queryKey: allyKeys.all(workspaceId) }).catch(() => undefined);
      setPendingCreate(null);
      setRetryPending(false);
      setCreatedAlly(ally);
      setFlow((current) => ({ ...current, step: 'basics' }));
      return true;
    } catch (error) {
      if (isInvalidOnboardingAttempt(error)) {
        setRetryPending(false);
        setCloudAttempt(null);
        setCloudAttemptBusy(true);
        setCloudAttemptRequest((current) => current + 1);
        setCloudMessage('The preview expired. We refreshed it. Review your reply and send it again.');
        return false;
      }
      if (isTransientCloudError(error)) {
        setRetryPending(true);
        setCloudMessage('We could not confirm the creation. Retry the saved reply.');
        return false;
      }
      setRetryPending(true);
      setCloudMessage(messageForCreateError(error));
      return false;
    } finally {
      if (activeCreateControllerRef.current === controller) {
        activeCreateControllerRef.current = null;
        if (mountedRef.current) setCloudSubmitting(false);
      }
    }
  }, [cloudAttempt, cloudInputKey, flow, pendingCreate, queryClient, session]);

  const handleCancelPending = useCallback(async () => {
    activeCreateControllerRef.current?.abort();
    const operation = ++createOperationRef.current;
    try {
      await pendingCommandStore.deleteCreate();
    } catch {
      if (mountedRef.current && operation === createOperationRef.current) {
        setCloudMessage('We could not clear the saved creation. Try again.');
      }
      return;
    }
    if (!mountedRef.current || operation !== createOperationRef.current) return;
    setPendingCreate(null);
    setRetryPending(false);
    if (sessionIdentityRef.current) {
      router.replace('/');
    } else {
      setCloudAttempt(null);
      setCloudMessage(null);
      setFlow(INITIAL_ONBOARDING_FLOW);
    }
  }, [router]);

  const handleNext = async () => {
    setHelpOpen(false);
    if (flow.step === 'personality') {
      setCloudAttempt(null);
      setCloudAttemptBusy(true);
      setCloudMessage(null);
    }
    await waitForKeyboardToHide();
    setFlow((current) => ({
      ...current,
      allyName: current.step === 'name' ? current.allyName.trim() : current.allyName,
      step: getNextOnboardingStep(current.step, current),
    }));
  };

  const handleAccountContinue = useCallback(async (draft: string) => {
    if (!cloudAttempt || cloudAttempt.inputKey !== cloudInputKey) {
      setCloudMessage('The preview expired. Review it again before continuing.');
      return;
    }

    const command = pendingCreate && commandMatches(pendingCreate, flow, cloudAttempt.attemptToken, draft)
        ? pendingCreate
        : createCommand(flow, cloudAttempt.attemptToken, draft);
    try {
      await pendingCommandStore.saveCreate(command);
      setPendingCreate(command);
    } catch {
      setCloudMessage('We could not save your Ally yet. Try again.');
      return;
    }

    if (session.nativeAuthCompletionMode === 'manual_code') {
      router.replace('/sign-in?returnTo=/allies/new/complete' as never);
      return;
    }
    try {
      const outcome = await session.startGoogleSignIn('/allies/new/complete');
      if (outcome.status === 'signed-in') {
        router.replace('/allies/new/complete' as never);
      } else if (outcome.status === 'canceled') {
        setCloudMessage('Google sign-in was cancelled. Your Ally is still saved.');
      } else {
        setCloudMessage('We could not complete Google sign-in. Your Ally is still saved; try again.');
      }
    } catch {
      setCloudMessage('We could not complete Google sign-in. Your Ally is still saved; try again.');
    }
  }, [cloudAttempt, cloudInputKey, flow, pendingCreate, router, session]);

  const handleBasicsComplete = useCallback(() => {
    setFlow((current) => ({ ...current, step: 'notifications' }));
  }, []);

  const handleNotificationsComplete = useCallback(() => {
    if (createdAlly) {
      router.replace(`/allies/${encodeURIComponent(createdAlly.id)}` as never);
      return;
    }
    router.replace('/allies' as never);
  }, [createdAlly, router]);

  const handleAllowNotifications = useCallback(async () => {
    try {
      await requestNotificationPermission();
    } finally {
      handleNotificationsComplete();
    }
  }, [handleNotificationsComplete]);

  const handleBack = useCallback(() => {
    setHelpOpen(false);
    if (flow.step === initialStep && onExit) {
      onExit();
      return;
    }
    Keyboard.dismiss();
    setFlow((current) => ({
      ...current,
      step: getPreviousOnboardingStep(current.step),
    }));
  }, [flow.step, initialStep, onExit]);

  useEffect(() => {
    if (!onExit) return undefined;

    const subscription = BackHandler.addEventListener('hardwareBackPress', () => {
      handleBack();
      return true;
    });

    return () => subscription.remove();
  }, [handleBack, onExit]);

  const step = flow.step;
  const accentColor = getOnboardingAccent(flow.selectedColor);

  if (step === 'welcome') {
    return (
      <OnboardingScreen
        accentColor={accentColor}
        onStart={() => router.navigate('/onboarding/name' as never)}
        onSignIn={() => router.push('/sign-in')}
      />
    );
  }

  if (step === 'preview') {
    const greeting = cloudAttempt?.inputKey === cloudInputKey ? cloudAttempt.greeting : '';
    return (
      <OnboardingPreviewScreen
        allyName={flow.allyName}
        allyShape={flow.allyShape}
        greeting={greeting}
        isSubmitting={cloudSubmitting || cloudAttemptBusy}
        onBack={handleBack}
        onAccountContinue={handleAccountContinue}
        onCancelPending={retryPending ? handleCancelPending : undefined}
        onReplySubmit={handleCloudReply}
        retryPending={retryPending}
        selectedColor={flow.selectedColor}
        statusMessage={cloudAttemptBusy ? null : cloudMessage}
        initialReply={pendingCreate?.reply}
        requiresAccount={session.status !== 'signed-in'}
      />
    );
  }

  if (step === 'basics') {
    return (
      <OnboardingBasicsScreen
        allyName={flow.allyName}
        allyShape={flow.allyShape}
        onComplete={handleBasicsComplete}
        selectedColor={flow.selectedColor}
      />
    );
  }

  if (step === 'notifications') {
    return (
      <OnboardingNotificationsScreen
        allyShape={flow.allyShape}
        onAllow={handleAllowNotifications}
        onSkip={handleNotificationsComplete}
        selectedColor={flow.selectedColor}
      />
    );
  }

  const chrome = getOnboardingChrome(step);
  const headerAllyVariant = getOnboardingHeaderAllyVariant(step);
  const canContinue =
    step === 'name'
      ? isAllyNameReady(flow.allyName)
      : step === 'look'
        ? isLookReady(flow)
        : step === 'job'
          ? isJobDescriptionReady(flow.jobDescription)
          : step === 'personality'
            ? isPersonalityReady(flow.personalities, flow.personalityNote)
            : false;
  const isFormStep = step === 'name' || step === 'look' || step === 'job' || step === 'personality';
  const onboardingContent = (
      <OnboardingShell
        accentColor={accentColor}
        centerContent={step === 'name'}
        footer={isFormStep ? (
            <PrimaryButton
              accentColor={accentColor}
              bottomMargin={0}
              disabled={isOnboardingFooterDisabled(step, canContinue, helpOpen)}
              label={step === 'personality' && canContinue ? 'Save' : 'Next'}
              onPress={handleNext}
            />
          ) : undefined}
        onBack={handleBack}
        progress={chrome.progress}
        title={chrome.title}
        titleAccessory={
          headerAllyVariant === 'none' ? undefined : headerAllyVariant === 'placeholder' ? (
            <Image
              accessibilityLabel="Placeholder Ally"
              contentFit="contain"
              source={require('@/assets/allies/icons/placeholder-rolly.svg')}
              style={styles.headerPlaceholder}
            />
          ) : (
            <OnboardingAllyPreview
              accessibilityLabel={`${flow.allyName || 'Your'} Ally preview`}
              color={flow.selectedColor}
              identity={flow.allyShape}
              size={40}
              artworkScale={ONBOARDING_HEADER_ALLY_ARTWORK_SCALE}
              state={step === 'personality' ? 'thinking' : 'idle'}
            />
          )
        }>
        {step === 'name' ? (
          <AllyNameScreen
            accentColor={accentColor}
            allyName={flow.allyName}
            onNameChange={(allyName) =>
              setFlow((current) => ({
                ...current,
                allyName: allyName.slice(0, MAX_NAME_LENGTH),
              }))
            }
            onNext={handleNext}
          />
        ) : step === 'look' ? (
          <OnboardingLookScreen
            allyShape={flow.allyShape}
            hasSwipedAvatar={flow.hasSwipedAvatar}
            selectedColor={flow.selectedColor}
            onColorChange={(selectedColor) => setFlow((current) => ({ ...current, selectedColor }))}
            onShapeChange={(allyShape) => setFlow((current) => ({ ...current, allyShape }))}
            onSwipe={() => setFlow((current) => ({ ...current, hasSwipedAvatar: true }))}
          />
        ) : step === 'job' ? (
          <OnboardingJobScreen
            accentColor={accentColor}
            jobDescription={flow.jobDescription}
            onHelpVisibilityChange={setHelpOpen}
            onJobDescriptionChange={(jobDescription) =>
              setFlow((current) => ({
                ...current,
                jobDescription: jobDescription.slice(0, MAX_JOB_DESCRIPTION_LENGTH),
              }))
            }
          />
        ) : step === 'personality' ? (
          <OnboardingPersonalityScreen
            accentColor={accentColor}
            onHelpVisibilityChange={setHelpOpen}
            personalityNote={flow.personalityNote}
            personalities={flow.personalities}
            onPersonalityNoteChange={(personalityNote) =>
              setFlow((current) => ({
                ...current,
                personalityNote: personalityNote.slice(0, MAX_PERSONALITY_NOTE_LENGTH),
              }))
            }
            onTogglePersonality={(personality: Personality) =>
              setFlow((current) => {
                const nextPersonalities = current.personalities.includes(personality)
                  ? current.personalities.filter((item) => item !== personality)
                  : [...current.personalities, personality];

                return {
                  ...current,
                  personalities: nextPersonalities,
                  personalityNote: getPersonalityNoteForSelection(nextPersonalities),
                };
              })
            }
          />
        ) : null}
      </OnboardingShell>
  );

  return onboardingContent;
}

const styles = StyleSheet.create({
  headerPlaceholder: {
    height: 40,
    width: 40,
  },
});
