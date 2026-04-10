import { colors, radius } from "../../theme";
import type { CSSProperties, ReactNode } from "react";

interface CardProps {
  accentColor?: string;
  children: ReactNode;
  style?: CSSProperties;
}

export default function Card({ accentColor, children, style }: CardProps) {
  return (
    <div style={{
      background: colors.surface,
      borderRadius: radius.md,
      border: `1px solid ${colors.border}`,
      borderTop: `3px solid ${accentColor || colors.border}`,
      padding: "20px",
      ...style,
    }}>
      {children}
    </div>
  );
}
