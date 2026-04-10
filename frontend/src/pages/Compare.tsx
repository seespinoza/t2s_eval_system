import { useState } from "react";
import { useRuns } from "../hooks/useRuns";
import { useCompareMetrics } from "../hooks/useMetrics";
import Card from "../components/ui/Card";
import MonoLabel from "../components/ui/MonoLabel";
import RunBar from "../components/ui/RunBar";
import { colors, fonts, spacing } from "../theme";

const METRICS_ROWS = [
  { key: "pct_passed", label: "Pass %", format: (v: number) => `${v?.toFixed(1)}%`, best: "max" },
  { key: "pct_failed", label: "Fail %", format: (v: number) => `${v?.toFixed(1)}%`, best: "min" },
  { key: "pct_rule_violation", label: "Rule Violation %", format: (v: number) => `${v?.toFixed(1)}%`, best: "min" },
  { key: "avg_runtime_ms", label: "Avg Runtime", format: (v: number) => v ? `${(v / 1000).toFixed(1)}s` : "—", best: "min" },
  { key: "total", label: "Questions", format: (v: number) => String(v ?? "—"), best: null },
];

export default function Compare() {
  const { runs } = useRuns(50);
  const [selected, setSelected] = useState<string[]>([]);
  const data = useCompareMetrics(selected);

  const toggle = (id: string) => {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : prev.length < 10 ? [...prev, id] : prev
    );
  };

  return (
    <div>
      <h1 style={{ fontFamily: fonts.heading, fontSize: 28, marginBottom: spacing.xl }}>Compare Runs</h1>

      <MonoLabel>Select Runs (up to 10)</MonoLabel>
      <div style={{ display: "flex", flexWrap: "wrap", gap: spacing.sm, marginBottom: spacing.xl }}>
        {runs.map((r) => (
          <button
            key={r.id}
            onClick={() => toggle(r.id)}
            style={{
              padding: "6px 14px", borderRadius: 100, cursor: "pointer", fontSize: 13,
              background: selected.includes(r.id) ? `${colors.runs}25` : "transparent",
              border: `1px solid ${selected.includes(r.id) ? colors.runs : colors.border}`,
              color: selected.includes(r.id) ? colors.runs : colors.textMuted,
              fontFamily: fonts.body,
            }}
          >
            {r.name || r.id.slice(0, 8)}
          </button>
        ))}
      </div>

      {data.length > 0 && (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={thStyle}>Metric</th>
                {data.map((m) => (
                  <th key={m.run_id} style={thStyle}>{m.run_name || m.run_id.slice(0, 8)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr>
                <td style={tdStyle}>Run Bar</td>
                {data.map((m) => (
                  <td key={m.run_id} style={{ ...tdStyle, minWidth: 140 }}>
                    <RunBar pctPassed={m.pct_passed} pctFailed={m.pct_failed} pctRuleViolation={m.pct_rule_violation} />
                  </td>
                ))}
              </tr>
              {METRICS_ROWS.map(({ key, label, format, best }) => {
                const vals = data.map((m) => (m as any)[key] as number);
                const extremeVal = best === "max" ? Math.max(...vals) : best === "min" ? Math.min(...vals) : null;
                return (
                  <tr key={key}>
                    <td style={tdStyle}>
                      <MonoLabel>{label}</MonoLabel>
                    </td>
                    {data.map((m, i) => {
                      const v = (m as any)[key];
                      const isBest = extremeVal !== null && v === extremeVal;
                      return (
                        <td key={m.run_id} style={{ ...tdStyle, color: isBest ? colors.passed : colors.text, fontWeight: isBest ? 700 : 400 }}>
                          {format(v)}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

const thStyle: React.CSSProperties = {
  textAlign: "left", padding: "10px 16px",
  borderBottom: `1px solid ${colors.border}`,
  color: colors.textMuted, fontFamily: "'DM Mono', monospace",
  fontSize: 11, textTransform: "uppercase", letterSpacing: "0.08em",
};

const tdStyle: React.CSSProperties = {
  padding: "10px 16px", borderBottom: `1px solid ${colors.border}`,
  fontSize: 14, fontFamily: "'DM Sans', sans-serif",
};
