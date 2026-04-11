import { useState, useEffect, useMemo } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ResponsiveContainer,
} from "recharts";
import { runsApi, metricsApi, type Run, type LlmCall, type LlmSummary } from "../api/client";
import Card from "../components/ui/Card";
import MonoLabel from "../components/ui/MonoLabel";
import { colors, fonts, spacing } from "../theme";

// ── Rolling average helper ────────────────────────────────────────────────────

function rollingAvg(values: (number | null)[], window: number): (number | null)[] {
  return values.map((_, i) => {
    const slice = values.slice(Math.max(0, i - window + 1), i + 1).filter((v): v is number => v !== null);
    return slice.length ? slice.reduce((a, b) => a + b, 0) / slice.length : null;
  });
}

// ── Stat tile ─────────────────────────────────────────────────────────────────

function StatTile({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <MonoLabel>{label}</MonoLabel>
      <span style={{ fontFamily: fonts.mono, fontSize: 22, color: colors.text }}>{value}</span>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function LlmUsage() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string>("");
  const [calls, setCalls] = useState<LlmCall[]>([]);
  const [summary, setSummary] = useState<LlmSummary | null>(null);
  const [loading, setLoading] = useState(false);

  // Load completed runs for the selector
  useEffect(() => {
    runsApi.list(50).then((all) => {
      const completed = all.filter((r) => r.status === "completed");
      setRuns(completed);
      if (completed.length > 0) setSelectedRunId(completed[0].id);
    }).catch(() => {});
  }, []);

  // Fetch calls + summary when run changes
  useEffect(() => {
    if (!selectedRunId) return;
    setLoading(true);
    Promise.all([
      metricsApi.llmCalls(selectedRunId),
      metricsApi.llmSummary(selectedRunId),
    ]).then(([c, s]) => {
      setCalls(c);
      setSummary(s);
    }).catch(() => {}).finally(() => setLoading(false));
  }, [selectedRunId]);

  // Build chart data — one point per call, ordered by called_at (already sorted)
  const chartData = useMemo(() => {
    const latencies = calls.map((c) => c.latency_ms);
    const tokens = calls.map((c) => c.total_tokens);
    const avgLat = rollingAvg(latencies, 10);
    return calls.map((c, i) => ({
      seq: i + 1,
      call_type: c.call_type,
      latency_ms: c.latency_ms,
      rolling_latency: avgLat[i] !== null ? Math.round(avgLat[i]!) : null,
      total_tokens: tokens[i],
    }));
  }, [calls]);

  // Unique call types for coloring the breakdown table
  const callTypes = summary ? Object.keys(summary.by_call_type) : [];
  const typeColors = [colors.runs, colors.questions, colors.seed, colors.review, colors.metrics, "#4ec9e0", "#e8e8e8"];

  const fmt = (n: number | null | undefined) =>
    n == null ? "—" : n >= 1_000_000 ? `${(n / 1_000_000).toFixed(2)}M` : n >= 1_000 ? `${(n / 1_000).toFixed(1)}K` : String(n);

  return (
    <div>
      <h1 style={{ fontFamily: fonts.heading, fontSize: 28, marginBottom: spacing.md }}>
        LLM Usage
      </h1>

      {/* Run selector */}
      <div style={{ marginBottom: spacing.xl, display: "flex", alignItems: "center", gap: spacing.md }}>
        <MonoLabel style={{ marginBottom: 0 }}>Run</MonoLabel>
        <select
          value={selectedRunId}
          onChange={(e) => setSelectedRunId(e.target.value)}
          style={{
            background: colors.surface, border: `1px solid ${colors.border}`,
            color: colors.text, padding: "6px 12px", borderRadius: 4,
            fontFamily: fonts.mono, fontSize: 13, minWidth: 280,
          }}
        >
          {runs.length === 0 && <option value="">No completed runs</option>}
          {runs.map((r) => (
            <option key={r.id} value={r.id}>
              {r.name || r.id.slice(0, 8)} — {r.completed_at ? new Date(r.completed_at).toLocaleDateString() : ""}
            </option>
          ))}
        </select>
      </div>

      {loading && <p style={{ color: colors.textMuted }}>Loading...</p>}

      {!loading && summary && (
        <>
          {/* Stats strip */}
          <Card accentColor={colors.metrics} style={{ marginBottom: spacing.xl }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: spacing.xl }}>
              <StatTile label="Total Calls" value={fmt(summary.totals.calls)} />
              <StatTile label="Input Tokens" value={fmt(summary.totals.input_tokens)} />
              <StatTile label="Output Tokens" value={fmt(summary.totals.output_tokens)} />
              <StatTile label="Total Tokens" value={fmt(summary.totals.total_tokens)} />
              <StatTile
                label="Avg Latency"
                value={summary.totals.avg_latency_ms != null ? `${summary.totals.avg_latency_ms.toFixed(0)} ms` : "—"}
              />
            </div>
          </Card>

          {/* Call type breakdown table */}
          <Card accentColor={colors.runs} style={{ marginBottom: spacing.xl }}>
            <MonoLabel>By Call Type</MonoLabel>
            <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: fonts.mono, fontSize: 13 }}>
              <thead>
                <tr style={{ color: colors.textMuted, textAlign: "left" }}>
                  {["Call Type", "Calls", "Input Tokens", "Output Tokens", "Total Tokens", "Avg Latency"].map((h) => (
                    <th key={h} style={{ padding: "6px 12px 10px 0", fontWeight: 500, fontSize: 11, letterSpacing: "0.06em", textTransform: "uppercase" }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {callTypes.map((ct, i) => {
                  const row = summary.by_call_type[ct];
                  const accent = typeColors[i % typeColors.length];
                  return (
                    <tr key={ct} style={{ borderTop: `1px solid ${colors.border}` }}>
                      <td style={{ padding: "8px 12px 8px 0" }}>
                        <span style={{
                          display: "inline-block", padding: "2px 8px", borderRadius: 10,
                          background: `${accent}22`, color: accent, fontSize: 12,
                        }}>{ct}</span>
                      </td>
                      <td style={{ padding: "8px 12px 8px 0", color: colors.text }}>{fmt(row.calls)}</td>
                      <td style={{ padding: "8px 12px 8px 0", color: colors.text }}>{fmt(row.input_tokens)}</td>
                      <td style={{ padding: "8px 12px 8px 0", color: colors.text }}>{fmt(row.output_tokens)}</td>
                      <td style={{ padding: "8px 12px 8px 0", color: colors.text }}>{fmt(row.total_tokens)}</td>
                      <td style={{ padding: "8px 12px 8px 0", color: colors.text }}>
                        {row.avg_latency_ms != null ? `${row.avg_latency_ms} ms` : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Card>

          {/* Charts */}
          {chartData.length > 0 && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: spacing.xl }}>
              {/* Latency per call */}
              <Card accentColor={colors.seed} style={{ minHeight: 300 }}>
                <MonoLabel>Latency (ms) per Call</MonoLabel>
                <p style={{ fontSize: 12, color: colors.textMuted, marginBottom: spacing.md }}>
                  Per-call latency with 10-call rolling average
                </p>
                <ResponsiveContainer width="100%" height={240}>
                  <LineChart data={chartData} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke={colors.border} />
                    <XAxis
                      dataKey="seq" stroke={colors.textMuted}
                      tick={{ fill: colors.textMuted, fontSize: 11, fontFamily: "'DM Mono', monospace" }}
                      label={{ value: "Call #", position: "insideBottom", offset: -2, fill: colors.textMuted, fontSize: 11 }}
                    />
                    <YAxis
                      stroke={colors.textMuted}
                      tick={{ fill: colors.textMuted, fontSize: 11, fontFamily: "'DM Mono', monospace" }}
                      width={52}
                    />
                    <Tooltip
                      contentStyle={{ background: colors.surface, border: `1px solid ${colors.border}`, fontFamily: "'DM Mono', monospace", fontSize: 12 }}
                      labelStyle={{ color: colors.textMuted }}
                      itemStyle={{ color: colors.text }}
                      formatter={(val: number | null) => val != null ? `${val} ms` : "—"}
                      labelFormatter={(seq: number) => `Call ${seq} — ${chartData[seq - 1]?.call_type ?? ""}`}
                    />
                    <Legend wrapperStyle={{ fontSize: 11, fontFamily: "'DM Mono', monospace" }} />
                    <Line
                      type="monotone" dataKey="latency_ms" name="Latency"
                      stroke={colors.seed} dot={false} strokeWidth={1.5} opacity={0.45}
                      connectNulls={false}
                    />
                    <Line
                      type="monotone" dataKey="rolling_latency" name="Rolling avg (10)"
                      stroke={colors.text} dot={false} strokeWidth={2}
                      connectNulls={true}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </Card>

              {/* Tokens per call */}
              <Card accentColor={colors.questions} style={{ minHeight: 300 }}>
                <MonoLabel>Tokens per Call</MonoLabel>
                <p style={{ fontSize: 12, color: colors.textMuted, marginBottom: spacing.md }}>
                  Total tokens (input + output) per call over time
                </p>
                <ResponsiveContainer width="100%" height={240}>
                  <LineChart data={chartData} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke={colors.border} />
                    <XAxis
                      dataKey="seq" stroke={colors.textMuted}
                      tick={{ fill: colors.textMuted, fontSize: 11, fontFamily: "'DM Mono', monospace" }}
                      label={{ value: "Call #", position: "insideBottom", offset: -2, fill: colors.textMuted, fontSize: 11 }}
                    />
                    <YAxis
                      stroke={colors.textMuted}
                      tick={{ fill: colors.textMuted, fontSize: 11, fontFamily: "'DM Mono', monospace" }}
                      width={52}
                    />
                    <Tooltip
                      contentStyle={{ background: colors.surface, border: `1px solid ${colors.border}`, fontFamily: "'DM Mono', monospace", fontSize: 12 }}
                      labelStyle={{ color: colors.textMuted }}
                      itemStyle={{ color: colors.text }}
                      labelFormatter={(seq: number) => `Call ${seq} — ${chartData[seq - 1]?.call_type ?? ""}`}
                    />
                    <Legend wrapperStyle={{ fontSize: 11, fontFamily: "'DM Mono', monospace" }} />
                    <Line
                      type="monotone" dataKey="total_tokens" name="Total tokens"
                      stroke={colors.questions} dot={false} strokeWidth={2}
                      connectNulls={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </Card>
            </div>
          )}

          {chartData.length === 0 && (
            <p style={{ color: colors.textMuted, fontFamily: fonts.mono, fontSize: 13 }}>
              No LLM call records for this run.
            </p>
          )}
        </>
      )}

      {!loading && !summary && selectedRunId && (
        <p style={{ color: colors.textMuted, fontFamily: fonts.mono, fontSize: 13 }}>
          No data available for this run.
        </p>
      )}
    </div>
  );
}
