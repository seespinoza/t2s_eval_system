import { useNavigate } from "react-router-dom";
import { useRuns } from "../hooks/useRuns";
import { useReviewQueue } from "../hooks/useReviewQueue";
import { useTimeseries } from "../hooks/useMetrics";
import Card from "../components/ui/Card";
import MonoLabel from "../components/ui/MonoLabel";
import RunBar from "../components/ui/RunBar";
import StatusBadge from "../components/ui/StatusBadge";
import { colors, fonts, spacing } from "../theme";
import { runsApi } from "../api/client";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";

export default function Dashboard() {
  const { runs, loading, reload } = useRuns(10);
  const { stats } = useReviewQueue();
  const timeseries = useTimeseries();
  const navigate = useNavigate();

  const latestCompleted = runs.find((r) => r.status === "completed");

  const handleNewRun = async () => {
    const run = await runsApi.create({ name: `Run ${new Date().toLocaleDateString()}` });
    await runsApi.start(run.id);
    reload();
  };

  const statCards = [
    { label: "Total Runs", value: runs.length, accent: colors.runs },
    {
      label: "Latest Pass Rate",
      value: latestCompleted ? `—` : "—",
      accent: colors.passed,
    },
    { label: "Pending Reviews", value: stats.pending, accent: colors.review },
  ];

  return (
    <div>
      <h1 style={{ fontFamily: fonts.heading, fontSize: 32, fontWeight: 700, marginBottom: spacing.xl }}>
        Evaluation Dashboard
      </h1>

      {/* Stat strip */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: spacing.md, marginBottom: spacing.xl }}>
        {statCards.map((s) => (
          <Card key={s.label} accentColor={s.accent}>
            <MonoLabel>{s.label}</MonoLabel>
            <span style={{ fontFamily: fonts.heading, fontSize: 28, fontWeight: 700 }}>{s.value}</span>
          </Card>
        ))}
      </div>

      {/* Actions */}
      <div style={{ display: "flex", gap: spacing.sm, marginBottom: spacing.xl }}>
        <button onClick={handleNewRun} style={btnStyle(colors.runs)}>+ New Run</button>
        <button onClick={() => navigate("/seed")} style={btnStyle(colors.seed)}>Seed Questions</button>
        <button onClick={() => navigate("/compare")} style={btnStyle(colors.metrics)}>Compare Runs</button>
      </div>

      {/* Trend chart */}
      {timeseries.length > 1 && (
        <Card accentColor={colors.metrics} style={{ marginBottom: spacing.xl }}>
          <MonoLabel>Pass Rate Trend</MonoLabel>
          <ResponsiveContainer width="100%" height={140}>
            <LineChart data={timeseries}>
              <XAxis dataKey="completed_at" tick={false} />
              <YAxis domain={[0, 100]} tick={{ fill: colors.textMuted, fontSize: 11 }} />
              <Tooltip
                contentStyle={{ background: colors.surface, border: `1px solid ${colors.border}`, borderRadius: 6 }}
                formatter={(v: number) => [`${v.toFixed(1)}%`, "Pass rate"]}
              />
              <Line type="monotone" dataKey="pct_passed" stroke={colors.passed} dot={false} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </Card>
      )}

      {/* Recent runs */}
      <MonoLabel>Recent Runs</MonoLabel>
      {loading ? (
        <p style={{ color: colors.textMuted }}>Loading...</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: spacing.sm }}>
          {runs.map((run) => (
            <Card
              key={run.id}
              accentColor={colors.runs}
              style={{ cursor: "pointer" }}
            >
              <div
                onClick={() => navigate(`/runs/${run.id}`)}
                style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}
              >
                <div>
                  <div style={{ fontWeight: 600, marginBottom: 4 }}>
                    {run.name || run.id.slice(0, 8)}
                    {run.resume_count > 0 && (
                      <span style={{ marginLeft: 8, fontSize: 11, color: colors.seed }}>
                        resumed ×{run.resume_count}
                      </span>
                    )}
                  </div>
                  <StatusBadge status={run.status} />
                </div>
                <div style={{ textAlign: "right", minWidth: 160 }}>
                  <RunBar pctPassed={0} pctFailed={0} pctRuleViolation={0} />
                  <span style={{ fontSize: 11, color: colors.textMuted, marginTop: 4, display: "block" }}>
                    {run.total_questions ?? "—"} questions
                  </span>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

function btnStyle(accent: string) {
  return {
    background: `${accent}18`,
    border: `1px solid ${accent}40`,
    color: accent,
    padding: "8px 16px",
    borderRadius: 6,
    cursor: "pointer",
    fontFamily: fonts.body,
    fontSize: 14,
    fontWeight: 500,
  } as const;
}
