import { Image } from 'expo-image';
import * as Crypto from 'expo-crypto';
import { useRouter } from 'expo-router';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { StyleSheet } from 'react-native';

import { isCloudError, type CloudError } from '@allies/cloud-client';

import { PrimaryButton } from '@/components/ui/primary-button';
import { useAllySessionIndex } from '@/features/allies/ally-session-index';
import { pendingCommandStore, type PendingCreateCommand } from '@/lib/pending-command-store';
import { useNativeSession } from '@/lib/session/session-context';
import { getMockGreeting, useMockApp } from '@/features/mock/mock-app';

import OnboardingScreen from './onboarding-screen';
import { AllyNameScreen } from './ally-name-screen';
import { OnboardingJobScreen } from './onboarding-job-screen';
import { OnboardingLookScreen } from './onboarding-look-screen';
import { OnboardingPersonalityScreen } from './onboarding-personality-screen';
import { OnboardingAllyPreview } from './onboarding-ally-preview';
import { OnboardingPreviewScreen } from './onboarding-preview-screen';
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
} from './onboarding-state';
import { toCreateAllyInput, toOnboardingAttemptInput } from './onboarding-cloud-input';

const PENDING_CREATE_LIFETIME_MS = 7 * 24 * 60 * 60 * 1000;

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
  return {
    kind: 'create',
    ...toCreateAllyInput(flow, attemptToken, reply),
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
  return JSON.stringify({
    name: command.name,
    job: command.job,
    personality: command.personality,
    appearance: command.appearance,
  }) === JSON.stringify(toOnboardingAttemptInput(flow));
}

function messageForCreateError(error: unknown): string {
  if (isCloudError(error) && error.kind === 'forbidden') return 'This Ally could not be created in the current workspace.';
  if (isCloudError(error) && error.kind === 'unauthorized') return 'Your sign-in expired. Sign in again to finish creating your Ally.';
  return 'We could not create your Ally. Try again.';
}

export default function OnboardingFlow() {
  const router = useRouter();
  const mock = useMockApp();
  const session = useNativeSession();
  const { addReachableAllyId } = useAllySessionIndex();
  const [flow, setFlow] = useState<OnboardingFlowState>(INITIAL_ONBOARDING_FLOW);
  const [personalityHelpOpen, setPersonalityHelpOpen] = useState(false);
  const [cloudAttempt, setCloudAttempt] = useState<{ inputKey: string; attemptToken: string; greeting: string } | null>(null);
  const [cloudAttemptBusy, setCloudAttemptBusy] = useState(false);
  const [cloudAttemptRequest, setCloudAttemptRequest] = useState(0);
  const [cloudMessage, setCloudMessage] = useState<string | null>(null);
  const [cloudSubmitting, setCloudSubmitting] = useState(false);
  const [retryPending, setRetryPending] = useState(false);
  const [pendingCreate, setPendingCreate] = useState<PendingCreateCommand | null>(null);
  const cloudInput = useMemo(() => toOnboardingAttemptInput(flow), [flow]);
  const cloudInputKey = JSON.stringify(cloudInput);

  useEffect(() => {
    if (mock.isMock) return undefined;
    if (flow.step !== 'welcome' || session.status !== 'signed-in' || !session.account) return;

    let active = true;
    void pendingCommandStore.readCreate(session.account.userId, session.account.workspace.id).then((command) => {
      if (!active || !command) return;
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
    });

    return () => {
      active = false;
    };
  }, [flow.step, mock.isMock, session.account, session.status]);

  useEffect(() => {
    if (mock.isMock || flow.step !== 'preview') return undefined;

    const controller = new AbortController();
    void (async () => {
      try {
        if (!session.accountClient) throw { kind: 'client' } satisfies CloudError;
        const attempt = await session.accountClient.beginOnboardingAttempt(cloudInput, controller.signal);
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
  }, [cloudAttemptRequest, cloudInput, cloudInputKey, flow.allyName, flow.jobDescription, flow.step, mock.isMock, session.accountClient]);

  const handleCloudReply = useCallback(async (reply: string): Promise<boolean> => {
    if (mock.isMock) {
      mock.createAlly({
        color: flow.selectedColor ?? '#FF5800',
        job: flow.jobDescription,
        name: flow.allyName.trim(),
        personality: flow.personalityNote,
        shape: flow.allyShape,
      }, reply);
      router.replace('/allies/mock-ally' as never);
      return true;
    }
    if (!cloudAttempt || cloudAttempt.inputKey !== cloudInputKey) {
      setCloudMessage('The preview expired. We are preparing a new one. Review your reply and send it again.');
      setCloudAttempt(null);
      setCloudAttemptBusy(true);
      setCloudAttemptRequest((current) => current + 1);
      return false;
    }

    try {
      let command = pendingCreate;
      if (command && !commandMatches(command, flow, cloudAttempt.attemptToken, reply)) {
        if (command.reply === reply && commandMatchesConfig(command, flow)) {
          command = { ...command, onboardingAttempt: cloudAttempt.attemptToken };
          await pendingCommandStore.saveCreate(command);
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
        }
        setPendingCreate(command);
      }

      if (session.status !== 'signed-in' || !session.account || !session.accountClient || !session.adapter) {
        router.replace('/sign-in?returnTo=/allies/new/complete' as never);
        return true;
      }

      setCloudSubmitting(true);
      const boundCommand = await pendingCommandStore.bindCreate(
        session.account.userId,
        session.account.workspace.id,
      );
      if (!boundCommand) {
        setPendingCreate(null);
        setRetryPending(false);
        setCloudMessage('Your saved Ally creation no longer belongs to this session. Start again.');
        return false;
      }

      const ally = await session.adapter.withRefresh(() => session.accountClient!.createAlly(
        session.account!.workspace.id,
        boundCommand,
        boundCommand.idempotencyKey,
      ));
      await pendingCommandStore.deleteCreate();
      setPendingCreate(null);
      setRetryPending(false);
      addReachableAllyId(ally.id);
      router.replace(`/allies/${ally.id}` as never);
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
      setCloudSubmitting(false);
    }
  }, [addReachableAllyId, cloudAttempt, cloudInputKey, flow, mock, pendingCreate, router, session]);

  const handleCancelPending = useCallback(async () => {
    try {
      await pendingCommandStore.deleteCreate();
    } catch {
      setCloudMessage('We could not clear the saved creation. Try again.');
      return;
    }
    setPendingCreate(null);
    setRetryPending(false);
    if (session.status === 'signed-in') {
      router.replace('/allies' as never);
    } else {
      setCloudAttempt(null);
      setCloudMessage(null);
      setFlow(INITIAL_ONBOARDING_FLOW);
    }
  }, [router, session.status]);

  const handleNext = () => {
    setPersonalityHelpOpen(false);
    if (flow.step === 'personality' && !mock.isMock) {
      setCloudAttempt(null);
      setCloudAttemptBusy(true);
      setCloudMessage('Preparing your Ally preview…');
    }
    setFlow((current) => ({
      ...current,
      allyName: current.step === 'name' ? current.allyName.trim() : current.allyName,
      step: getNextOnboardingStep(current.step, current),
    }));
  };

  const handleBack = () => {
    setPersonalityHelpOpen(false);
    setFlow((current) => ({
      ...current,
      step: getPreviousOnboardingStep(current.step),
    }));
  };

  const step = flow.step;
  const accentColor = getOnboardingAccent(flow.selectedColor);

  if (step === 'welcome') {
    return (
      <OnboardingScreen
        accentColor={accentColor}
        onStart={() => setFlow((current) => ({ ...current, step: 'name' }))}
        onSignIn={() => router.push('/sign-in')}
      />
    );
  }

  if (step === 'preview') {
    const greeting = mock.isMock
      ? getMockGreeting(flow.allyName, flow.jobDescription)
      : cloudAttempt?.inputKey === cloudInputKey ? cloudAttempt.greeting : '';
    return (
      <OnboardingPreviewScreen
        allyName={flow.allyName}
        allyShape={flow.allyShape}
        greeting={greeting}
        isSubmitting={mock.isMock ? false : cloudSubmitting || cloudAttemptBusy}
        onCancelPending={retryPending ? handleCancelPending : undefined}
        onReplySubmit={handleCloudReply}
        retryPending={retryPending}
        selectedColor={flow.selectedColor}
        statusMessage={mock.isMock ? null : cloudMessage}
        initialReply={pendingCreate?.reply}
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
  return (
    <OnboardingShell
      accentColor={accentColor}
      footer={isFormStep ? (
          <PrimaryButton
            accentColor={accentColor}
            bottomMargin={0}
            disabled={isOnboardingFooterDisabled(step, canContinue, personalityHelpOpen)}
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
          jobDescription={flow.jobDescription}
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
          onHelpVisibilityChange={setPersonalityHelpOpen}
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
}

const styles = StyleSheet.create({
  headerPlaceholder: {
    height: 40,
    width: 40,
  },
});
