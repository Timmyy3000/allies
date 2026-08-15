export function ProgressRing({ progress }: { progress: number }) {
  const clamped = Math.min(1, Math.max(0, progress));
  const radius = 16.4137;
  const circumference = 2 * Math.PI * radius;
  const dash = circumference * clamped;

  return (
    <svg
      width="40"
      height="40"
      viewBox="0 0 40 40"
      fill="none"
      aria-hidden
      style={{ left: 315, top: 24, width: 40, height: 40, position: "absolute" }}
    >
      <circle cx="20" cy="20" r={radius} fill="none" stroke="#f3f3f3" strokeWidth="3.5863" />
      <circle
        cx="20"
        cy="20"
        r={radius}
        fill="none"
        stroke="#ff5800"
        strokeWidth="3.5863"
        strokeDasharray={`${dash} ${circumference}`}
        strokeLinecap="round"
        transform="rotate(-90 20 20)"
        style={{ transition: "stroke-dasharray 420ms cubic-bezier(0.34, 1.72, 0.36, 1)" }}
      />
    </svg>
  );
}
