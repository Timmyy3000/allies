export const INACTIVE_CTA = "#d9d9d9";
export const DEFAULT_ACCENT = "#ff5800";

export function NextButton({
  label,
  active,
  color = DEFAULT_ACCENT,
  onClick,
  bottom = 24,
}: {
  label: string;
  active: boolean;
  color?: string;
  onClick?: () => void;
  bottom?: number;
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
        borderRadius: 60,
        backgroundColor: active ? color : INACTIVE_CTA,
        display: "flex",
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "center",
        left: 20,
        bottom,
        width: 335,
        height: 48,
        position: "absolute",
        padding: 10,
        border: 0,
        cursor: active ? "pointer" : "default",
        color: "#fff",
        fontSize: 18,
        fontWeight: 600,
        letterSpacing: -0.52,
        lineHeight: "24px",
      }}
    >
      {label}
    </button>
  );
}
