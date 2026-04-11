import { useState, useEffect } from "react";
import { seederApi, type Stratum, type SeedReport } from "../api/client";
import Card from "../components/ui/Card";
import MonoLabel from "../components/ui/MonoLabel";
import { colors, fonts, spacing } from "../theme";

export default function Seed() {
  const [strata, setStrata] = useState<Stratum[]>([]);
  const [report, setReport] = useState<SeedReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState<"idle" | "dry_run" | "done">("idle");

  useEffect(() => {
    seederApi.strata().then(setStrata).catch(() => {});
  }, []);

  const handleDryRun = async () => {
    setLoading(true);
    const r = await seederApi.dryRun();
    setReport(r);
    setMode("dry_run");
    setLoading(false);
  };

  const handleSeed = async () => {
    setLoading(true);
    const r = await seederApi.run();
    setReport(r);
    setMode("done");
    seederApi.strata().then(setStrata);
    setLoading(false);
  };

  const needsWork = strata.filter((s) => s.needed > 0);

  return (
    <div>
      <h1 style={{ fontFamily: fonts.heading, fontSize: 28, marginBottom: spacing.xl }}>Question Seeder</h1>

      {/* Strata table */}
      <Card accentColor={colors.seed} style={{ marginBottom: spacing.xl }}>
        <MonoLabel>Strata — Current vs Target</MonoLabel>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr>
              {["Table", "Task", "Tone", "Current", "Target", "Needed"].map((h) => (
                <th key={h} style={{ textAlign: "left", padding: "6px 12px", borderBottom: `1px solid ${colors.border}`, color: colors.textMuted, fontFamily: fonts.mono, fontSize: 10, letterSpacing: "0.08em", textTransform: "uppercase" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {strata.map((s) => (
              <tr key={`${s.table_name}-${s.task}-${s.tone}`}>
                <td style={tdS}>{s.table_name}</td>
                <td style={tdS}>{s.task}</td>
                <td style={{ ...tdS, color: toneColor(s.tone), fontFamily: fonts.mono }}>{s.tone}</td>
                <td style={tdS}>{s.current_count}</td>
                <td style={tdS}>{s.target_count}</td>
                <td style={{ ...tdS, color: s.needed > 0 ? colors.review : colors.passed, fontWeight: s.needed > 0 ? 700 : 400 }}>
                  {s.needed}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      {/* Action buttons */}
      <div style={{ display: "flex", gap: spacing.sm, marginBottom: spacing.xl }}>
        <button disabled={loading || needsWork.length === 0} onClick={handleDryRun} style={seedBtn(colors.seed)}>
          {loading && mode !== "done" ? "Running..." : "Dry Run (Preview)"}
        </button>
        <button disabled={loading || needsWork.length === 0} onClick={handleSeed} style={seedBtn(colors.questions)}>
          {loading && mode === "done" ? "Seeding..." : "Execute Seed"}
        </button>
      </div>

      {/* Report */}
      {report && (
        <Card accentColor={mode === "done" ? colors.questions : colors.seed}>
          <MonoLabel>{mode === "done" ? "Seed Complete" : "Dry Run Preview"}</MonoLabel>
          <div style={{ display: "flex", gap: spacing.xl, marginBottom: spacing.lg }}>
            {[
              ["Strata Processed", report.strata_processed],
              ["Generated", report.questions_generated],
              ["Written", report.questions_written],
              ["Skipped (dupe)", report.skipped_duplicate],
            ].map(([label, val]) => (
              <div key={label as string}>
                <MonoLabel>{label as string}</MonoLabel>
                <span style={{ fontFamily: fonts.heading, fontSize: 22 }}>{val}</span>
              </div>
            ))}
          </div>

          {report.strata_detail.map((d) => (
            <div key={`${d.table_name}-${d.task}-${d.tone}`} style={{ marginBottom: spacing.md, borderTop: `1px solid ${colors.border}`, paddingTop: spacing.sm }}>
              <MonoLabel>
                {d.table_name} / {d.task} /
                <span style={{ color: toneColor(d.tone) }}> {d.tone}</span>
                {" "}— {d.needed} needed, {d.generated} generated
              </MonoLabel>
              {d.proposed.length > 0 && (
                <ul style={{ margin: 0, paddingLeft: 20 }}>
                  {d.proposed.map((q, i) => (
                    <li key={i} style={{ fontSize: 13, color: colors.text, marginBottom: 4 }}>{q}</li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </Card>
      )}
    </div>
  );
}

const tdS: React.CSSProperties = {
  padding: "7px 12px",
  borderBottom: `1px solid ${colors.border}`,
};

function toneColor(tone: string): string {
  return tone === "casual" ? "#f5a623" : tone === "formal" ? "#7c6af7" : "#888";
}

function seedBtn(accent: string): React.CSSProperties {
  return {
    padding: "8px 20px", background: `${accent}18`,
    border: `1px solid ${accent}50`, color: accent,
    cursor: "pointer", borderRadius: 6, fontSize: 14, fontWeight: 500,
  };
}
