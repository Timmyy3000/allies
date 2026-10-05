import {
  forwardRef,
  useCallback,
  useRef,
  type MouseEventHandler,
} from "react";

type OnboardingHelpTriggerProps = {
  accent: string;
  muted: string;
  softStrong: string;
  ariaLabel: string;
  expanded: boolean;
  controls: string;
  testId: string;
  onClick: MouseEventHandler<HTMLButtonElement>;
};

export const OnboardingHelpTrigger = forwardRef<
  HTMLButtonElement,
  OnboardingHelpTriggerProps
>(function OnboardingHelpTrigger(
  { accent, muted, softStrong, ariaLabel, expanded, controls, testId, onClick },
  ref,
) {
  return (
    <button
      ref={ref}
      type="button"
      aria-label={ariaLabel}
      aria-expanded={expanded}
      aria-controls={controls}
      data-testid={testId}
      className="onboarding-help-trigger"
      style={{ backgroundColor: softStrong }}
      onClick={onClick}
    >
      <svg
        aria-hidden="true"
        width="20"
        height="20"
        viewBox="0 0 19.33 19.33"
        fill="none"
      >
        <circle cx="9.67" cy="9.67" r="9.67" fill={muted} />
        <circle
          cx="9.67"
          cy="9.67"
          r="8.67"
          stroke={accent}
          strokeWidth="2"
        />
        <path
          d="M6.9 6.49C7.42 5.08 8.63 4.5 9.81 4.5 11 4.5 12.23 5.35 12.23 6.91 12.23 9.29 9.81 8.87 9.44 11"
          stroke={accent}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <circle cx="9.39" cy="14.42" r="1.33" fill={accent} />
      </svg>
    </button>
  );
});

export function useOnboardingHelpFocus() {
  const triggerRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const restoreFocus = useRef(false);

  const requestRestoreFocus = useCallback(() => {
    restoreFocus.current = true;
  }, []);

  const onExitComplete = useCallback(() => {
    if (!restoreFocus.current) return;
    restoreFocus.current = false;
    triggerRef.current?.focus();
  }, []);

  return {
    triggerRef,
    closeRef,
    requestRestoreFocus,
    onExitComplete,
  };
}
