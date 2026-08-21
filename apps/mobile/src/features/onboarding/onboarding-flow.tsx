import { Image } from 'expo-image';
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { StyleSheet } from 'react-native';

import { PrimaryButton } from '@/components/ui/primary-button';

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
  type Personality,
  type OnboardingFlowState,
} from './onboarding-state';

export default function OnboardingFlow() {
  const router = useRouter();
  const [flow, setFlow] = useState<OnboardingFlowState>(INITIAL_ONBOARDING_FLOW);
  const [personalityHelpOpen, setPersonalityHelpOpen] = useState(false);

  const handleNext = () => {
    setPersonalityHelpOpen(false);
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
    return (
      <OnboardingPreviewScreen
        allyName={flow.allyName}
        allyShape={flow.allyShape}
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
