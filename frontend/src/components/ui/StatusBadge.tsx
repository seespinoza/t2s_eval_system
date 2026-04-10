import { colors, fonts } from "../../theme";

const OUTCOME_COLORS: Record<string, string> = {
  passed: colors.passed,
  failed: colors.failed,
  rule_violation: colors.rule_violation,
  low_confidence_pass: colors.low_confidence_pass,
  // Run statuses
  pending: colors.textMuted,
  running: colors.seed,
  completed: colors.passed,
  cancelled: colors.failed,
};

const LABELS: Record<string, string> = {
  low_confidence_pass: "low conf pass",
  rule_violation: "rule violation",
};

export default function StatusBadge({ status }: { status: string }) {
  const color = OUTCOME_COLORS[status] || colors.textMuted;
  const label = LABELS[status] || status;
  return (
    <span style={{
      display: "inline-block",
      padding: "2px 8px",
      borderRadius: 100,
      border: `1px solid ${color}40`,
      background: `${color}18`,
      color,
      fontFamily: fonts.mono,
      fontSize: "10px",
      letterSpacing: "0.05em",
      textTransform: "uppercase",
      fontWeight: 500,
      whiteSpace: "nowrap",
    }}>
      {label}
    </span>
  );
}
