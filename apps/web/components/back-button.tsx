export function BackButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      aria-label="Back"
      data-testid="back-button"
      onClick={onClick}
      style={{
        borderRadius: 100,
        backgroundColor: "#f3f3f3",
        left: 20,
        top: 24,
        width: 40,
        height: 40,
        position: "absolute",
        border: 0,
        cursor: "pointer",
        padding: 0,
      }}
    >
      <svg
        width="8"
        height="14"
        viewBox="0 0 8 14"
        fill="none"
        style={{ position: "absolute", left: 15, top: 13 }}
      >
        <path
          d="M6.25 12.5L0 6.25 6.25 0"
          stroke="#212121"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </button>
  );
}
