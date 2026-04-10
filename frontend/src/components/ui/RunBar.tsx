import { colors } from "../../theme";

interface RunBarProps {
  pctPassed: number;
  pctFailed: number;
  pctRuleViolation: number;
  height?: number;
}

export default function RunBar({ pctPassed, pctFailed, pctRuleViolation, height = 6 }: RunBarProps) {
  const pctLowConf = Math.max(0, 100 - pctPassed - pctFailed - pctRuleViolation);
  return (
    <div style={{ display: "flex", height, borderRadius: 3, overflow: "hidden", background: colors.border }}>
      {pctPassed > 0 && <div style={{ width: `${pctPassed}%`, background: colors.passed }} />}
      {pctRuleViolation > 0 && <div style={{ width: `${pctRuleViolation}%`, background: colors.rule_violation }} />}
      {pctLowConf > 0 && <div style={{ width: `${pctLowConf}%`, background: colors.low_confidence_pass }} />}
      {pctFailed > 0 && <div style={{ width: `${pctFailed}%`, background: colors.failed }} />}
    </div>
  );
}
