import { useParams } from "react-router-dom";
import { useState, useEffect } from "react";
import { useRun } from "../hooks/useRuns";
import { runsApi, type Result, type RunMetrics } from "../api/client";
import Card from "../components/ui/Card";
import MonoLabel from "../components/ui/MonoLabel";
import StatusBadge from "../components/ui/StatusBadge";
import DotRating from "../components/ui/DotRating";
import RunBar from "../components/ui/RunBar";
import { colors, fonts, spacing } from "../theme";

export default function RunDetail() {
  const { id } = useParams<{ id: string }>();
  const { run, loading } = useRun(id!);
  const [results, setResults] = useState<Result[]>([]);
  const [metrics, setMetrics] = useState<RunMetrics | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [outcomeFilter, setOutcomeFilter] = useState("");
  const [page, setPage] = useState(1);

  useEffect(() => {
    if (!id) return;
    runsApi.results(id, { outcome: outcomeFilter, page: String(page), page_size: "50" })
      .then(setResults).catch(() => {});
    runsApi.metrics(id).then(setMetrics).catch(() => {});
  }, [id, outcomeFilter, page]);

  if (loading || !run) return <p style={{ color: colors.textMuted }}>Loading...</p>;

  const outcomes = ["", "passed", "failed", "rule_violation", "low_confidence_pass"];

  return (
    <div>
      <h1 style={{ fontFamily: fonts.heading, fontSize: 28, marginBottom: spacing.md }}>
        {run.name || run.id.slice(0, 8)}
      </h1>
      <div style={{ display: "flex", gap: spacing.sm, marginBottom: spacing.xl, alignItems: "center", flexWrap: "wrap" }}>
        <StatusBadge status={run.status} />
        {run.agent_version && (
          <span style={{ fontSize: 11, fontFamily: fonts.mono, color: colors.seed,
            background: `${colors.seed}15`, padding: "2px 8px", borderRadius: 4 }}>
            {run.agent_version}
          </span>
        )}
        {run.resume_count > 0 && (
          <span style={{ fontSize: 12, color: colors.seed }}>Resumed ×{run.resume_count}</span>
        )}
        {run.completed_at && (
          <span style={{ fontSize: 12, color: colors.textMuted }}>
            Completed {new Date(run.completed_at).toLocaleString()}
          </span>
        )}
      </div>
      {run.description && (
        <p style={{ fontSize: 13, color: colors.textMuted, fontStyle: "italic",
          marginBottom: spacing.xl, marginTop: `-${spacing.md}` }}>
          {run.description}
        </p>
      )}
      {run.question_set_id && (
        <p style={{ fontSize: 12, color: colors.textMuted, marginBottom: spacing.xl,
          marginTop: run.description ? `-${spacing.md}` : `-${spacing.md}` }}>
          <span style={{ fontFamily: fonts.mono }}>QUESTION SET</span>{" "}
          <span style={{ color: colors.text }}>{run.question_set_id}</span>
        </p>
      )}

      {/* Metrics panel */}
      {metrics && (
        <Card accentColor={colors.metrics} style={{ marginBottom: spacing.xl }}>
          <MonoLabel>Metrics</MonoLabel>
          <RunBar
            pctPassed={metrics.pct_passed}
            pctFailed={metrics.pct_failed}
            pctRuleViolation={metrics.pct_rule_violation}
            height={10}
          />
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: spacing.md, marginTop: spacing.md }}>
            {[
              { label: "Passed", val: `${metrics.pct_passed.toFixed(1)}%`, color: colors.passed },
              { label: "Failed", val: `${metrics.pct_failed.toFixed(1)}%`, color: colors.failed },
              { label: "Rule Violation", val: `${metrics.pct_rule_violation.toFixed(1)}%`, color: colors.rule_violation },
              { label: "Avg Runtime", val: metrics.avg_runtime_ms ? `${(metrics.avg_runtime_ms / 1000).toFixed(1)}s` : "—", color: colors.textMuted },
            ].map(({ label, val, color }) => (
              <div key={label}>
                <MonoLabel>{label}</MonoLabel>
                <span style={{ color, fontSize: 20, fontWeight: 700, fontFamily: fonts.heading }}>{val}</span>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Filter */}
      <div style={{ display: "flex", gap: spacing.sm, marginBottom: spacing.md }}>
        {outcomes.map((o) => (
          <button
            key={o || "all"}
            onClick={() => { setOutcomeFilter(o); setPage(1); }}
            style={{
              padding: "4px 12px", borderRadius: 100, fontSize: 12, cursor: "pointer",
              background: outcomeFilter === o ? `${colors.runs}30` : "transparent",
              border: `1px solid ${outcomeFilter === o ? colors.runs : colors.border}`,
              color: outcomeFilter === o ? colors.runs : colors.textMuted,
              fontFamily: fonts.mono,
            }}
          >
            {o || "all"}
          </button>
        ))}
      </div>

      {/* Results table */}
      <div style={{ display: "flex", flexDirection: "column", gap: spacing.sm }}>
        {results.map((r) => (
          <Card key={r.id} accentColor={colors.runs} style={{ padding: "12px 16px" }}>
            <div
              onClick={() => setExpanded(expanded === r.id ? null : r.id)}
              style={{ cursor: "pointer", display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}
            >
              <div style={{ flex: 1, marginRight: spacing.md }}>
                <div style={{ fontSize: 14, marginBottom: 4 }}>{r.nlq_snapshot}</div>
                <div style={{ display: "flex", gap: spacing.sm, alignItems: "center" }}>
                  <StatusBadge status={r.outcome} />
                  {r.route && <span style={{ fontSize: 11, color: colors.textMuted }}>{r.route}</span>}
                  {r.runtime_ms && <span style={{ fontSize: 11, color: colors.textMuted }}>{(r.runtime_ms / 1000).toFixed(1)}s</span>}
                </div>
              </div>
              {r.judge_confidence !== null && (
                <DotRating score={r.judge_confidence} />
              )}
            </div>

            {expanded === r.id && (
              <div style={{ marginTop: spacing.md, borderTop: `1px solid ${colors.border}`, paddingTop: spacing.md }}>
                {r.sql_generated && (
                  <div style={{ marginBottom: spacing.md }}>
                    <MonoLabel>Generated SQL</MonoLabel>
                    <pre style={{ background: "#111", padding: 12, borderRadius: 4, fontSize: 12, overflowX: "auto", color: colors.text }}>
                      {r.sql_generated}
                    </pre>
                  </div>
                )}
                {r.judge_reasoning && (
                  <div style={{ marginBottom: spacing.md }}>
                    <MonoLabel>Judge Reasoning</MonoLabel>
                    <p style={{ fontSize: 13, color: colors.text, lineHeight: 1.6 }}>{r.judge_reasoning}</p>
                  </div>
                )}
                {r.error_message && (
                  <div>
                    <MonoLabel>Error</MonoLabel>
                    <p style={{ fontSize: 13, color: colors.failed }}>{r.error_message}</p>
                  </div>
                )}
              </div>
            )}
          </Card>
        ))}
      </div>

      {/* Pagination */}
      <div style={{ display: "flex", gap: spacing.sm, marginTop: spacing.lg }}>
        <button disabled={page === 1} onClick={() => setPage(page - 1)} style={pageBtn}>← Prev</button>
        <span style={{ color: colors.textMuted, lineHeight: "32px", fontSize: 13 }}>Page {page}</span>
        <button onClick={() => setPage(page + 1)} style={pageBtn}>Next →</button>
      </div>
    </div>
  );
}

const pageBtn: React.CSSProperties = {
  padding: "4px 12px", background: "transparent",
  border: `1px solid ${colors.border}`, color: colors.textMuted,
  cursor: "pointer", borderRadius: 4, fontSize: 13,
};
