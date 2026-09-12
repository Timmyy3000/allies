"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useOnboardingStore } from "../_store/onboarding-store";
import { OnboardingLayout } from "./onboarding-layout";
import { StepHeading } from "./step-heading";
import { WanderAllies } from "./wander-allies";

export function IntroductionScreen({ onBack, allies }: { onBack: () => void; allies: ReactNode[] }) {
  const goTo = useOnboardingStore((state) => state.goTo);
  const sceneRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 320, height: 400 });

  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene) return;
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize((current) => current.width === width && current.height === height ? current : { width, height });
    });
    observer.observe(scene);
    return () => observer.disconnect();
  }, []);

  const agents = useMemo(() => allies.map((ally, index) => ({
    id: String(index),
    start: {
      left: [0.12, 0.72, 0.2, 0.7][index] * (size.width - 64),
      top: [0.12, 0.32, 0.65, 0.8][index] * (size.height - 60),
    },
    render: () => ally,
  })), [allies, size]);

  return (
    <OnboardingLayout testId="onboarding-introduction" progress={0.1} onBack={onBack}
      nextActive nextLabel="Next" onNext={() => goTo("job")}>
      <StepHeading>Everyone needs a little help from time to time</StepHeading>
      <div ref={sceneRef} className="onboarding-intro-scene" aria-hidden="true">
        <WanderAllies artW={size.width} artH={size.height} agents={agents} />
      </div>
    </OnboardingLayout>
  );
}
