import { useFonts } from 'expo-font';
import { useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { PrimaryButton } from '@/components/ui/primary-button';

import OnboardingScreen from './onboarding-screen';
import { AllyNameScreen } from './ally-name-screen';
import { OnboardingJobScreen } from './onboarding-job-screen';
import { OnboardingLookScreen } from './onboarding-look-screen';
import { OnboardingPersonalityScreen } from './onboarding-personality-screen';
import { OnboardingAllyPreview } from './onboarding-ally-preview';
import { OnboardingPreviewScreen } from './onboarding-preview-screen';
import { getOnboardingChrome, OnboardingShell } from './onboarding-shell';
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
  const [flow, setFlow] = useState<OnboardingFlowState>(INITIAL_ONBOARDING_FLOW);
  const [fontsLoaded] = useFonts({
    OpenRundeMedium: require('@/assets/allies/fonts/OpenRunde-Medium.otf'),
    OpenRundeSemibold: require('@/assets/allies/fonts/OpenRunde-Semibold.otf'),
  });

  if (!fontsLoaded) {
    return <View style={styles.loading} />;
  }

  const handleNext = () => {
    setFlow((current) => ({
      ...current,
      allyName: current.step === 'name' ? current.allyName.trim() : current.allyName,
      step: getNextOnboardingStep(current.step, current),
    }));
  };

  const handleBack = () => {
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
            disabled={!canContinue}
            label={step === 'personality' && canContinue ? 'Save' : 'Next'}
            onPress={handleNext}
          />
        ) : undefined}
      onBack={handleBack}
      progress={chrome.progress}
      title={chrome.title}
      titleAccessory={
        step === 'name' ? undefined : (
          <OnboardingAllyPreview
            accessibilityLabel={`${flow.allyName || 'Your'} Ally preview`}
            color={flow.selectedColor}
            identity={flow.allyShape}
            size={40}
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
  loading: {
    backgroundColor: '#FFFFFF',
    flex: 1,
  },
});
