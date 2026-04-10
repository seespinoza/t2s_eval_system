import { colors, fonts } from "../../theme";
import type { ReactNode } from "react";

export default function MonoLabel({ children }: { children: ReactNode }) {
  return (
    <span style={{
      fontFamily: fonts.mono,
      fontSize: "10px",
      fontWeight: 500,
      letterSpacing: "0.12em",
      textTransform: "uppercase",
      color: colors.textMuted,
      display: "block",
      marginBottom: "8px",
    }}>
      {children}
    </span>
  );
}
