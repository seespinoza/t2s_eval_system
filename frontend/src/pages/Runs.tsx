import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useRuns } from "../hooks/useRuns";
import { runsApi, type Run, type RunStatus } from "../api/client";
import Card from "../components/ui/Card";
import MonoLabel from "../components/ui/MonoLabel";
import StatusBadge from "../components/ui/StatusBadge";
import { colors, fonts, spacing } from "../theme";

const STATUS_TABS: Array<{ label: string; value: RunStatus | "" }> = [
  { label: "All", value: "" },
  { label: "Pending", value: "pending" },
  { label: "Running", value: "running" },
  { label: "Completed", value: "completed" },
  { label: "Failed", value: "failed" },
  { label: "Cancelled", value: "cancelled" },
];

export default function Runs() {
  const navigate = useNavigate();
  const { runs, loading, reload } = useRuns(100);
  const [statusFilter, setStatusFilter] = useState<RunStatus | "">("");
  const [actionPending, setActionPending] = useState<string | null>(null);

  const filtered = statusFilter ? runs.filter((r) => r.status === statusFilter) : runs;

  const handleNewRun = async () => {
    const run = await runsApi.create({ name: `Run ${new Date().toLocaleDateString()}` });
    await runsApi.start(run.id);
    reload();
  };

  const handleStart = async (e: React.MouseEvent, run: Run) => {
    e.stopPropagation();
    setActionPending(run.id);
    try {
      await runsApi.start(run.id);
      reload();
    } finally {
      setActionPending(null);
    }
  };

  const handleCancel = async (e: React.MouseEvent, run: Run) => {
    e.stopPropagation();
    setActionPending(run.id);
    try {
      await runsApi.cancel(run.id);
      reload();
    } finally {
      setActionPending(null);
    }
  };

  const handleDelete = async (e: React.MouseEvent, run: Run) => {
    e.stopPropagation();
    if (!confirm(`Delete run "${run.name || run.id.slice(0, 8)}"?`)) return;
    setActionPending(run.id);
    try {
      await runsApi.delete(run.id);
      reload();
    } finally {
      setActionPending(null);
    }
  };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: spacing.xl }}>
        <h1 style={{ fontFamily: fonts.heading, fontSize: 32, fontWeight: 700, margin: 0 }}>Runs</h1>
        <button onClick={handleNewRun} style={btnStyle(colors.runs)}>+ New Run</button>
      </div>

      {/* Status filter tabs */}
      <div style={{ display: "flex", gap: spacing.sm, marginBottom: spacing.lg, flexWrap: "wrap" }}>
        {STATUS_TABS.map(({ label, value }) => {
          const count = value ? runs.filter((r) => r.status === value).length : runs.length;
          const active = statusFilter === value;
          return (
            <button
              key={label}
              onClick={() => setStatusFilter(value)}
              style={{
                padding: "5px 14px", borderRadius: 100, fontSize: 12, cursor: "pointer",
                background: active ? `${colors.runs}25` : "transparent",
                border: `1px solid ${active ? colors.runs : colors.border}`,
                color: active ? colors.runs : colors.textMuted,
                fontFamily: fonts.mono,
                letterSpacing: "0.05em",
              }}
            >
              {label.toUpperCase()} {count > 0 && <span style={{ opacity: 0.6 }}>({count})</span>}
            </button>
          );
        })}
      </div>

      {/* Run list */}
      {loading ? (
        <p style={{ color: colors.textMuted }}>Loading...</p>
      ) : filtered.length === 0 ? (
        <p style={{ color: colors.textMuted }}>
          {statusFilter ? `No ${statusFilter} runs.` : "No runs yet. Click + New Run to get started."}
        </p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: spacing.sm }}>
          {filtered.map((run) => (
            <Card
              key={run.id}
              accentColor={colors.runs}
              style={{ cursor: "pointer" }}
            >
              <div
                onClick={() => navigate(`/runs/${run.id}`)}
                style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}
              >
                {/* Left: name + meta */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: spacing.sm, marginBottom: 6 }}>
                    <span style={{ fontWeight: 600, fontSize: 15 }}>
                      {run.name || run.id.slice(0, 8)}
                    </span>
                    <StatusBadge status={run.status} />
                    {run.resume_count > 0 && (
                      <span style={{ fontSize: 11, color: colors.seed }}>resumed ×{run.resume_count}</span>
                    )}
                  </div>
                  <div style={{ display: "flex", gap: spacing.md, flexWrap: "wrap" }}>
                    <span style={{ fontSize: 12, color: colors.textMuted }}>
                      {run.total_questions != null ? `${run.total_questions} questions` : "—"}
                    </span>
                    {run.agent_version && (
                      <span style={{ fontSize: 11, fontFamily: fonts.mono, color: colors.seed,
                        background: `${colors.seed}15`, padding: "1px 6px", borderRadius: 4 }}>
                        {run.agent_version}
                      </span>
                    )}
                    {run.status === "running" && run.progress && (
                      <span style={{ fontSize: 12, color: colors.seed }}>
                        {run.progress.completed}/{run.progress.total} completed
                      </span>
                    )}
                    <span style={{ fontSize: 12, color: colors.textMuted }}>
                      {new Date(run.created_at).toLocaleString()}
                    </span>
                  </div>
                  {run.description && (
                    <div style={{ fontSize: 12, color: colors.textMuted, marginTop: 4, fontStyle: "italic" }}>
                      {run.description}
                    </div>
                  )}
                </div>

                {/* Right: action button */}
                <div style={{ marginLeft: spacing.md, flexShrink: 0 }} onClick={(e) => e.stopPropagation()}>
                  {run.status === "pending" && (
                    <button
                      onClick={(e) => handleStart(e, run)}
                      disabled={actionPending === run.id}
                      style={actionBtn(colors.runs)}
                    >
                      {actionPending === run.id ? "Starting…" : "Start"}
                    </button>
                  )}
                  {run.status === "running" && (
                    <button
                      onClick={(e) => handleCancel(e, run)}
                      disabled={actionPending === run.id}
                      style={actionBtn(colors.review)}
                    >
                      {actionPending === run.id ? "Cancelling…" : "Cancel"}
                    </button>
                  )}
                  {(run.status === "completed" || run.status === "failed" || run.status === "cancelled") && (
                    <button
                      onClick={(e) => handleDelete(e, run)}
                      disabled={actionPending === run.id}
                      style={actionBtn(colors.failed)}
                    >
                      {actionPending === run.id ? "Deleting…" : "Delete"}
                    </button>
                  )}
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

function actionBtn(accent: string) {
  return {
    padding: "4px 12px",
    borderRadius: 4,
    fontSize: 12,
    cursor: "pointer",
    background: `${accent}18`,
    border: `1px solid ${accent}50`,
    color: accent,
    fontFamily: fonts.mono,
  } as const;
}
