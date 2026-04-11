import { useState, useMemo, useEffect } from "react";
import { useRuns } from "../hooks/useRuns";
import { useCompareMetrics } from "../hooks/useMetrics";
import { metricsApi, type RunMetrics, type StratumMetrics, type QuestionCompareRow } from "../api/client";
import Card from "../components/ui/Card";
import MonoLabel from "../components/ui/MonoLabel";
import StatusBadge from "../components/ui/StatusBadge";
import DotRating from "../components/ui/DotRating";
import RunBar from "../components/ui/RunBar";
import { colors, fonts, spacing } from "../theme";

// ── Metrics table rows ────────────────────────────────────────────────────────

const METRICS_ROWS = [
  { key: "pct_passed",        label: "Pass %",           format: (v: number) => `${v?.toFixed(1)}%`,                         best: "max" },
  { key: "pct_failed",        label: "Fail %",           format: (v: number) => `${v?.toFixed(1)}%`,                         best: "min" },
  { key: "pct_rule_violation",label: "Rule Violation %", format: (v: number) => `${v?.toFixed(1)}%`,                         best: "min" },
  { key: "avg_runtime_ms",    label: "Avg Runtime",      format: (v: number) => v ? `${(v / 1000).toFixed(1)}s` : "—",       best: "min" },
  { key: "total",             label: "Questions",        format: (v: number) => String(v ?? "—"),                            best: null  },
];

function MetricsTable({ data, nameKey = "run_name" }: {
  data: Array<Record<string, any>>;
  nameKey?: string;
}) {
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th style={thStyle}>Metric</th>
            {data.map((m) => (
              <th key={m.run_id} style={thStyle}>{m[nameKey] || m.run_id.slice(0, 8)}</th>
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
            const vals = data.map((m) => m[key] as number);
            const extremeVal = best === "max" ? Math.max(...vals) : best === "min" ? Math.min(...vals) : null;
            return (
              <tr key={key}>
                <td style={tdStyle}><MonoLabel>{label}</MonoLabel></td>
                {data.map((m) => {
                  const v = m[key];
                  const isBest = extremeVal !== null && v === extremeVal && data.length > 1;
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
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function Compare() {
  const { runs } = useRuns(50);
  const [selected, setSelected] = useState<string[]>([]);
  const data = useCompareMetrics(selected);

  // ── Stratum filter state ───────────────────────────────────────────────────
  const [stratumTable, setStratumTable] = useState("");
  const [stratumTask,  setStratumTask]  = useState("");
  const [stratumTone,  setStratumTone]  = useState("");
  const [stratumData,  setStratumData]  = useState<StratumMetrics[]>([]);

  // Derive available filter options from already-loaded metrics_json
  const stratumOptions = useMemo(() => {
    const tables = new Set<string>();
    const tasks  = new Set<string>();
    const tones  = new Set<string>();
    data.forEach((m) => {
      const mj = (m as any).metrics_json;
      if (!mj) return;
      Object.keys(mj.by_table || {}).forEach((k) => tables.add(k));
      Object.keys(mj.by_task  || {}).forEach((k) => tasks.add(k));
      Object.keys(mj.by_tone  || {}).forEach((k) => tones.add(k));
    });
    return {
      tables: Array.from(tables).sort(),
      tasks:  Array.from(tasks).sort(),
      tones:  Array.from(tones).sort(),
    };
  }, [data]);

  const stratumActive = !!(stratumTable || stratumTask || stratumTone);

  useEffect(() => {
    if (!selected.length || !stratumActive) { setStratumData([]); return; }
    metricsApi.compareStratum(selected, {
      table: stratumTable || undefined,
      task:  stratumTask  || undefined,
      tone:  stratumTone  || undefined,
    }).then(setStratumData).catch(() => {});
  }, [selected, stratumTable, stratumTask, stratumTone, stratumActive]);

  // ── Question search state ──────────────────────────────────────────────────
  const [searchInput,   setSearchInput]   = useState("");
  const [searchQuery,   setSearchQuery]   = useState("");
  const [searchResults, setSearchResults] = useState<QuestionCompareRow[]>([]);
  const [searching,     setSearching]     = useState(false);
  const [expanded,      setExpanded]      = useState<string | null>(null); // "questionId:runId"

  const runSearch = async () => {
    if (!selected.length || !searchInput.trim()) return;
    setSearchQuery(searchInput.trim());
    setSearching(true);
    setExpanded(null);
    try {
      const rows = await metricsApi.compareQuestions(selected, searchInput.trim());
      setSearchResults(rows);
    } catch {
      setSearchResults([]);
    } finally {
      setSearching(false);
    }
  };

  const toggle = (id: string) =>
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : prev.length < 10 ? [...prev, id] : prev
    );

  const runName = (id: string) => {
    const r = runs.find((x) => x.id === id);
    return r?.name || id.slice(0, 8);
  };

  return (
    <div>
      <h1 style={{ fontFamily: fonts.heading, fontSize: 28, marginBottom: spacing.xl }}>Compare Runs</h1>

      {/* Run selector */}
      <MonoLabel>Select Runs (up to 10)</MonoLabel>
      <div style={{ display: "flex", flexWrap: "wrap", gap: spacing.sm, marginBottom: spacing.xl }}>
        {runs.map((r) => (
          <button key={r.id} onClick={() => toggle(r.id)} style={{
            padding: "6px 14px", borderRadius: 100, cursor: "pointer", fontSize: 13,
            background: selected.includes(r.id) ? `${colors.runs}25` : "transparent",
            border: `1px solid ${selected.includes(r.id) ? colors.runs : colors.border}`,
            color: selected.includes(r.id) ? colors.runs : colors.textMuted,
            fontFamily: fonts.body,
          }}>
            {r.name || r.id.slice(0, 8)}
            {(r as any).agent_version && (
              <span style={{ marginLeft: 6, fontSize: 10, fontFamily: fonts.mono, opacity: 0.7 }}>
                {(r as any).agent_version}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* ── Overall metrics table ───────────────────────────────────────────── */}
      {data.length > 0 && (
        <>
          <MonoLabel>Overall Metrics</MonoLabel>
          <div style={{ marginBottom: spacing.xl }}>
            <MetricsTable data={data as any[]} />
          </div>
        </>
      )}

      {/* ── Stratum breakdown ───────────────────────────────────────────────── */}
      {data.length > 0 && (
        <div style={{ marginBottom: spacing.xl }}>
          <MonoLabel>Breakdown by Stratum</MonoLabel>
          <div style={{ display: "flex", gap: spacing.sm, marginTop: spacing.sm, marginBottom: spacing.md, flexWrap: "wrap" }}>
            {[
              { label: "Table", value: stratumTable, set: setStratumTable, opts: stratumOptions.tables },
              { label: "Task",  value: stratumTask,  set: setStratumTask,  opts: stratumOptions.tasks  },
              { label: "Tone",  value: stratumTone,  set: setStratumTone,  opts: stratumOptions.tones  },
            ].map(({ label, value, set, opts }) => (
              <div key={label} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <span style={{ fontSize: 10, fontFamily: fonts.mono, color: colors.textMuted,
                  textTransform: "uppercase", letterSpacing: "0.08em" }}>{label}</span>
                <select
                  value={value}
                  onChange={(e) => set(e.target.value)}
                  style={{
                    background: colors.surface, border: `1px solid ${value ? colors.runs : colors.border}`,
                    color: value ? colors.text : colors.textMuted, borderRadius: 6,
                    padding: "5px 10px", fontSize: 13, fontFamily: fonts.body, cursor: "pointer",
                    minWidth: 140,
                  }}
                >
                  <option value="">All {label}s</option>
                  {opts.map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
              </div>
            ))}
            {stratumActive && (
              <button
                onClick={() => { setStratumTable(""); setStratumTask(""); setStratumTone(""); }}
                style={{ alignSelf: "flex-end", padding: "5px 12px", borderRadius: 6,
                  background: "transparent", border: `1px solid ${colors.border}`,
                  color: colors.textMuted, fontSize: 12, cursor: "pointer", fontFamily: fonts.mono }}
              >
                Clear
              </button>
            )}
          </div>

          {stratumActive && stratumData.length > 0 && (
            <MetricsTable data={stratumData as any[]} />
          )}
          {stratumActive && stratumData.length === 0 && (
            <p style={{ color: colors.textMuted, fontSize: 13 }}>No results for this stratum combination.</p>
          )}
          {!stratumActive && (
            <p style={{ color: colors.textMuted, fontSize: 13 }}>
              Select one or more filters above to see metrics for that stratum.
            </p>
          )}
        </div>
      )}

      {/* ── Question comparison ─────────────────────────────────────────────── */}
      {selected.length > 0 && (
        <div>
          <MonoLabel>Question Comparison</MonoLabel>
          <div style={{ display: "flex", gap: spacing.sm, marginTop: spacing.sm, marginBottom: spacing.md }}>
            <input
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && runSearch()}
              placeholder="Search by question text or question ID prefix…"
              style={{
                flex: 1, background: colors.surface, border: `1px solid ${colors.border}`,
                color: colors.text, borderRadius: 6, padding: "8px 12px",
                fontSize: 13, fontFamily: fonts.body, outline: "none",
              }}
            />
            <button
              onClick={runSearch}
              disabled={!searchInput.trim() || searching}
              style={{
                padding: "8px 18px", borderRadius: 6, cursor: "pointer",
                background: `${colors.runs}20`, border: `1px solid ${colors.runs}60`,
                color: colors.runs, fontSize: 13, fontFamily: fonts.body,
              }}
            >
              {searching ? "Searching…" : "Search"}
            </button>
          </div>

          {searchQuery && !searching && searchResults.length === 0 && (
            <p style={{ color: colors.textMuted, fontSize: 13 }}>
              No results found for "{searchQuery}".
            </p>
          )}

          {searchResults.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: spacing.sm }}>
              {searchResults.map((row) => (
                <Card key={row.question_id} accentColor={colors.metrics} style={{ padding: 0, overflow: "hidden" }}>
                  {/* Question header */}
                  <div style={{ padding: "12px 16px", borderBottom: `1px solid ${colors.border}` }}>
                    <div style={{ fontSize: 14, marginBottom: 4 }}>{row.nlq}</div>
                    <div style={{ display: "flex", gap: spacing.sm }}>
                      {row.tone && (
                        <span style={{ fontSize: 11, fontFamily: fonts.mono, color: colors.textMuted }}>
                          {row.tone}
                        </span>
                      )}
                      <span style={{ fontSize: 11, fontFamily: fonts.mono, color: colors.textMuted }}>
                        {row.question_id.slice(0, 8)}
                      </span>
                    </div>
                  </div>

                  {/* Per-run results columns */}
                  <div style={{ display: "grid", gridTemplateColumns: `repeat(${selected.length}, 1fr)` }}>
                    {selected.map((runId, i) => {
                      const r = row.results[runId];
                      const cellKey = `${row.question_id}:${runId}`;
                      const isExpanded = expanded === cellKey;
                      return (
                        <div
                          key={runId}
                          style={{
                            padding: "12px 16px",
                            borderLeft: i > 0 ? `1px solid ${colors.border}` : undefined,
                          }}
                        >
                          {/* Run name label */}
                          <div style={{ fontSize: 10, fontFamily: fonts.mono, color: colors.textMuted,
                            textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>
                            {runName(runId)}
                          </div>

                          {r ? (
                            <>
                              <div style={{ display: "flex", alignItems: "center", gap: spacing.sm, marginBottom: 6 }}>
                                <StatusBadge status={r.outcome} />
                                {r.judge_confidence !== null && r.judge_confidence !== undefined && (
                                  <DotRating score={r.judge_confidence} />
                                )}
                              </div>
                              {r.runtime_ms && (
                                <div style={{ fontSize: 11, color: colors.textMuted, marginBottom: 6 }}>
                                  {(r.runtime_ms / 1000).toFixed(1)}s
                                  {r.route && ` · ${r.route}`}
                                </div>
                              )}
                              <button
                                onClick={() => setExpanded(isExpanded ? null : cellKey)}
                                style={{ fontSize: 11, fontFamily: fonts.mono, background: "transparent",
                                  border: "none", color: colors.runs, cursor: "pointer", padding: 0 }}
                              >
                                {isExpanded ? "▲ hide" : "▼ details"}
                              </button>
                              {isExpanded && (
                                <div style={{ marginTop: spacing.sm, borderTop: `1px solid ${colors.border}`, paddingTop: spacing.sm }}>
                                  {r.sql_generated && (
                                    <div style={{ marginBottom: spacing.sm }}>
                                      <MonoLabel>SQL</MonoLabel>
                                      <pre style={{ background: "#111", padding: 10, borderRadius: 4,
                                        fontSize: 11, overflowX: "auto", color: colors.text, margin: 0 }}>
                                        {r.sql_generated}
                                      </pre>
                                    </div>
                                  )}
                                  {r.judge_reasoning && (
                                    <div style={{ marginBottom: spacing.sm }}>
                                      <MonoLabel>Reasoning</MonoLabel>
                                      <p style={{ fontSize: 12, color: colors.text, lineHeight: 1.6, margin: 0 }}>
                                        {r.judge_reasoning}
                                      </p>
                                    </div>
                                  )}
                                  {r.error_message && (
                                    <div>
                                      <MonoLabel>Error</MonoLabel>
                                      <p style={{ fontSize: 12, color: colors.failed, margin: 0 }}>
                                        {r.error_message}
                                      </p>
                                    </div>
                                  )}
                                </div>
                              )}
                            </>
                          ) : (
                            <span style={{ fontSize: 12, color: colors.textMuted, fontStyle: "italic" }}>
                              Not evaluated
                            </span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </Card>
              ))}
            </div>
          )}
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
