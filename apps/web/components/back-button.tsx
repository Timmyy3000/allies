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
        top: 68,
        width: 40,
        height: 40,
        position: "absolute",
        border: 0,
        cursor: "pointer",
        padding: 0,
      }}
    >
      <svg
        width="18"
        height="18"
        viewBox="0 0 18 18"
        fill="none"
        style={{ position: "absolute", left: 11, top: 11 }}
      >
        <path
          d="M11.75 3L5.5 9.25L11.75 15.5"
          stroke="#212121"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </button>
  );
}
