import { colors } from "../../theme";

interface DotRatingProps {
  score: number;  // 0.0 – 1.0
  accentColor?: string;
  size?: number;
}

export default function DotRating({ score, accentColor = colors.runs, size = 8 }: DotRatingProps) {
  const filled = Math.round(score * 10);
  return (
    <div style={{ display: "flex", gap: 3, alignItems: "center" }}>
      {Array.from({ length: 10 }, (_, i) => (
        <div
          key={i}
          style={{
            width: size, height: size,
            borderRadius: "50%",
            background: i < filled ? accentColor : colors.border,
            transition: "background 0.15s",
          }}
        />
      ))}
      <span style={{ marginLeft: 6, fontSize: 12, color: colors.textMuted, fontFamily: "'DM Mono', monospace" }}>
        {score.toFixed(2)}
      </span>
    </div>
  );
}
