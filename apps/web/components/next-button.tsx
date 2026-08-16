export const ONBOARDING_COLORS = {
  activeCta: "#FF5800",
  inactiveCta: "#D9D9D9",
} as const;

export const ONBOARDING_LAYOUT = {
  inlinePadding: 20,
  // Keep the authored 812px frame exact, but reclaim vertical space on
  // short mobile browser viewports instead of letting the header and CTA
  // collapse toward the middle of the screen.
  topPadding: "clamp(52px, 8.375dvh, 68px)",
  headingTop: "clamp(112px, 16.25dvh, 132px)",
  bottomPadding: "clamp(58px, 12.315dvh, 100px)",
} as const;

export const ONBOARDING_CTA = {
  height: 48,
  borderRadius: 60,
  padding: 10,
  gap: 10,
  fontFamily: "var(--font-open-runde), sans-serif",
  fontSize: 18,
  fontWeight: 600,
  lineHeight: "100%",
  letterSpacing: -0.7,
} as const;

// Keep these names available to screens that use the shared onboarding tokens.
export const DEFAULT_ACCENT = ONBOARDING_COLORS.activeCta;
export const INACTIVE_CTA = ONBOARDING_COLORS.inactiveCta;

function hexToRgba(color: string, alpha: number) {
  const normalized = color.replace("#", "");
  const red = Number.parseInt(normalized.slice(0, 2), 16);
  const green = Number.parseInt(normalized.slice(2, 4), 16);
  const blue = Number.parseInt(normalized.slice(4, 6), 16);

  if ([red, green, blue].some((channel) => Number.isNaN(channel))) {
    return `rgba(255, 88, 0, ${alpha})`;
  }

  return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
}

export function getAccentPalette(color?: string | null) {
  const accent = /^#[\da-f]{6}$/i.test(color ?? "") ? color! : DEFAULT_ACCENT;

  return {
    accent,
    soft: hexToRgba(accent, 0.1),
    softStrong: hexToRgba(accent, 0.16),
    muted: hexToRgba(accent, 0.4),
  };
}

export function NextButton({
  label,
  active,
  color = DEFAULT_ACCENT,
  onClick,
  bottom = ONBOARDING_LAYOUT.bottomPadding,
}: {
  label: string;
  active: boolean;
  color?: string;
  onClick?: () => void;
  bottom?: number | string;
}) {
  return (
    <button
      type="button"
      data-testid="next-button"
      data-active={active ? "true" : "false"}
      disabled={!active}
      onClick={onClick}
      className="onboarding-next"
      style={{
        borderRadius: ONBOARDING_CTA.borderRadius,
        backgroundColor: active ? color : INACTIVE_CTA,
        display: "flex",
        flexDirection: "row",
        gap: ONBOARDING_CTA.gap,
        alignItems: "center",
        justifyContent: "center",
        left: ONBOARDING_LAYOUT.inlinePadding,
        right: ONBOARDING_LAYOUT.inlinePadding,
        bottom,
        width: "auto",
        height: ONBOARDING_CTA.height,
        boxSizing: "border-box",
        position: "absolute",
        padding: ONBOARDING_CTA.padding,
        border: 0,
        cursor: active ? "pointer" : "default",
        color: "#fff",
        fontFamily: ONBOARDING_CTA.fontFamily,
        fontSize: ONBOARDING_CTA.fontSize,
        fontWeight: ONBOARDING_CTA.fontWeight,
        letterSpacing: ONBOARDING_CTA.letterSpacing,
        lineHeight: ONBOARDING_CTA.lineHeight,
      }}
    >
      {label}
    </button>
  );
}
