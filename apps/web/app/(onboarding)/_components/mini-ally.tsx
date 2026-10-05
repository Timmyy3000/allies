const CURSOR =
  "M25.8723 8.1633C28.7683 9.2356 28.7523 13.3397 25.8445 14.3857L17.6873 17.3219C17.5143 17.3847 17.3813 17.5195 17.3221 17.6847L14.3844 25.8445C13.3383 28.7519 9.2337 28.7685 8.1614 25.8727L0.2632 4.6066C0.225 4.5034 0.1859 4.4006 0.1532 4.2955-0.639 1.755 1.7753-0.6558 4.3218 0.1625 4.4342 0.1986 4.5445 0.2414 4.6553 0.2824L25.8723 8.1633Z";

export function MiniAlly({
  left,
  top,
  fill,
  faceLeft = 26,
  flipCursor = false,
}: {
  left: number | string;
  top: number | string;
  fill: string;
  faceLeft?: number;
  flipCursor?: boolean;
}) {
  return (
    <div
      style={{
        overflow: "hidden",
        left,
        top,
        width: 62,
        height: 60,
        position: "absolute",
      }}
    >
      <div
        style={{
          borderRadius: 100,
          backgroundColor: fill,
          left: faceLeft,
          top: 24,
          width: 36,
          height: 36,
          position: "absolute",
        }}
      />
      <div
        style={{
          overflow: "hidden",
          transform: flipCursor ? "scale(-1,1)" : undefined,
          transformOrigin: flipCursor ? "0 0" : undefined,
          left: flipCursor ? 60 : 0,
          top: 0,
          width: 36,
          height: 36,
          position: "absolute",
        }}
      >
        <svg
          viewBox="0 0 28.03 28.03"
          fill="none"
          style={{ width: "78%", height: "78%", margin: "12%" }}
        >
          <path d={CURSOR} style={{ fill }} />
        </svg>
      </div>
    </div>
  );
}

export function FaceMark({
  size = 160,
  look = "right",
  stroke = "#121212",
  fill = "#fff",
}: {
  size?: number;
  look?: "right" | "left" | "up" | "down";
  stroke?: string;
  fill?: string;
}) {
  const offset = {
    right: { x: 8, y: 0 },
    left: { x: -8, y: 0 },
    up: { x: 0, y: -8 },
    down: { x: 0, y: 8 },
  }[look];

  return (
    <svg width={size} height={size} viewBox="0 0 160 160" fill="none">
      <circle
        cx="80"
        cy="80"
        r="74"
        fill={fill}
        stroke={stroke}
        strokeWidth={stroke === "#a0a0a0" ? 8 : 12}
      />
      <g transform={`translate(${offset.x} ${offset.y})`}>
        <ellipse cx="62" cy="68" rx="12" ry="20.7" fill={stroke} />
        <ellipse cx="98" cy="68" rx="12" ry="20.7" fill={stroke} />
      </g>
    </svg>
  );
}

export function AllyMark({
  size = 160,
  look = "right",
  wash,
  stroke = "#121212",
}: {
  size?: number;
  look?: "right" | "left" | "up" | "down";
  wash?: string | null;
  stroke?: string;
}) {
  const face = wash ? size * (109 / 160) : size;

  return (
    <div
      data-testid={wash ? "avatar-wash" : undefined}
      className="ally-mark"
      style={{
        width: size,
        height: size,
        borderRadius: "50%",
        backgroundColor: wash ?? "transparent",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        overflow: "hidden",
        flexShrink: 0,
      }}
    >
      <div
        className="ally-mark-face"
        style={{
          width: face,
          height: face,
          display: "flex",
        }}
      >
        <FaceMark size={face} look={look} stroke={stroke} fill="#fff" />
      </div>
    </div>
  );
}
