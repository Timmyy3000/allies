export function BackButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      aria-label="Back"
      data-testid="back-button"
      onClick={onClick}
      style={{
        borderRadius: 100,
        backgroundColor: "var(--surface)",
        width: 40,
        height: 40,
        display: "grid",
        placeItems: "center",
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
        style={{ display: "block" }}
      >
        <path
          d="M11.75 3L5.5 9.25L11.75 15.5"
          stroke="var(--text-primary)"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </button>
  );
}
