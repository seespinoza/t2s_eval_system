import { useState } from "react";
import { useQuestions } from "../hooks/useQuestions";
import { questionsApi, type Question } from "../api/client";
import Card from "../components/ui/Card";
import MonoLabel from "../components/ui/MonoLabel";
import StatusBadge from "../components/ui/StatusBadge";
import { colors, fonts, spacing } from "../theme";

export default function Questions() {
  const [filters, setFilters] = useState<Record<string, string>>({});
  const { questions, loading, reload } = useQuestions(filters);
  const [editing, setEditing] = useState<Question | null>(null);
  const [editForm, setEditForm] = useState({ nlq: "", tone: "neutral", status: "active", notes: "" });

  const openEdit = (q: Question) => {
    setEditing(q);
    setEditForm({ nlq: q.nlq, tone: q.tone || "neutral", status: q.status, notes: q.notes || "" });
  };

  const saveEdit = async () => {
    if (!editing) return;
    await questionsApi.update(editing.id, editForm);
    setEditing(null);
    reload();
  };

  const handleExport = async () => {
    const res = await questionsApi.exportCsv();
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "questions.csv"; a.click();
  };

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const result = await questionsApi.importCsv(file);
    alert(`Applied: ${result.applied} | Errors: ${result.parse_errors?.length + result.apply_errors?.length}`);
    reload();
  };

  const handleCheckLeakage = async (id: string) => {
    await questionsApi.checkLeakage(id);
    reload();
  };

  return (
    <div>
      <h1 style={{ fontFamily: fonts.heading, fontSize: 28, marginBottom: spacing.xl }}>Question Bank</h1>

      {/* Filters */}
      <div style={{ display: "flex", gap: spacing.sm, marginBottom: spacing.lg, flexWrap: "wrap" }}>
        {["active", "monitoring"].map((s) => (
          <button
            key={s}
            onClick={() => setFilters(f => ({ ...f, status: f.status === s ? "" : s }))}
            style={{
              padding: "4px 12px", borderRadius: 100, fontSize: 12, cursor: "pointer",
              background: filters.status === s ? `${colors.questions}25` : "transparent",
              border: `1px solid ${filters.status === s ? colors.questions : colors.border}`,
              color: filters.status === s ? colors.questions : colors.textMuted,
              fontFamily: fonts.mono,
            }}
          >
            {s}
          </button>
        ))}
        {(["casual", "neutral", "formal"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setFilters(f => ({ ...f, tone: f.tone === t ? "" : t }))}
            style={{
              padding: "4px 12px", borderRadius: 100, fontSize: 12, cursor: "pointer",
              background: filters.tone === t ? `${toneColor(t)}25` : "transparent",
              border: `1px solid ${filters.tone === t ? toneColor(t) : colors.border}`,
              color: filters.tone === t ? toneColor(t) : colors.textMuted,
              fontFamily: fonts.mono,
            }}
          >
            {t}
          </button>
        ))}
        <button
          onClick={() => setFilters(f => ({ ...f, leakage_checked: f.leakage_checked === "false" ? "" : "false" }))}
          style={{
            padding: "4px 12px", borderRadius: 100, fontSize: 12, cursor: "pointer",
            background: filters.leakage_checked === "false" ? `${colors.review}25` : "transparent",
            border: `1px solid ${filters.leakage_checked === "false" ? colors.review : colors.border}`,
            color: filters.leakage_checked === "false" ? colors.review : colors.textMuted,
            fontFamily: fonts.mono,
          }}
        >
          unchecked
        </button>
      </div>

      {/* CSV controls */}
      <div style={{ display: "flex", gap: spacing.sm, marginBottom: spacing.xl }}>
        <button onClick={handleExport} style={actionBtn(colors.questions)}>Export CSV</button>
        <label style={{ ...actionBtn(colors.seed) as any, cursor: "pointer" }}>
          Import CSV
          <input type="file" accept=".csv" style={{ display: "none" }} onChange={handleImport} />
        </label>
        <button onClick={() => questionsApi.checkLeakageBatch().then(reload)} style={actionBtn(colors.review)}>
          Check Leakage (All Unchecked)
        </button>
      </div>

      {/* Table */}
      {loading ? (
        <p style={{ color: colors.textMuted }}>Loading...</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: spacing.xs }}>
          {questions.map((q) => (
            <Card key={q.id} accentColor={colors.questions} style={{ padding: "10px 16px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: spacing.md }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 14, marginBottom: 4 }}>{q.nlq}</div>
                  <div style={{ display: "flex", gap: spacing.sm, alignItems: "center", flexWrap: "wrap" }}>
                    <StatusBadge status={q.status} />
                    <span style={{ fontSize: 11, color: toneColor(q.tone), fontFamily: fonts.mono, border: `1px solid ${toneColor(q.tone)}50`, borderRadius: 100, padding: "1px 7px" }}>{q.tone}</span>
                    <span style={{ fontSize: 11, color: colors.textMuted, fontFamily: fonts.mono }}>{q.table_name} / {q.task}</span>
                    {q.is_seeded && <span style={{ fontSize: 11, color: colors.seed, fontFamily: fonts.mono }}>seeded</span>}
                    <span style={{ fontSize: 11, color: q.leakage_checked ? colors.passed : colors.review, fontFamily: fonts.mono }}>
                      {q.leakage_checked ? "✓ leakage ok" : "⚠ not checked"}
                    </span>
                  </div>
                </div>
                <div style={{ display: "flex", gap: spacing.xs }}>
                  <button onClick={() => openEdit(q)} style={rowBtn}>Edit</button>
                  {!q.leakage_checked && (
                    <button onClick={() => handleCheckLeakage(q.id)} style={rowBtn}>Check</button>
                  )}
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* Edit slide-over */}
      {editing && (
        <div style={{
          position: "fixed", inset: 0, background: "#000a", zIndex: 100,
          display: "flex", alignItems: "center", justifyContent: "center",
        }} onClick={() => setEditing(null)}>
          <div
            onClick={(e) => e.stopPropagation()}
            style={{ background: colors.surface, border: `1px solid ${colors.border}`, borderRadius: 10, padding: 24, width: 520, maxWidth: "90vw" }}
          >
            <h3 style={{ fontFamily: fonts.heading, marginBottom: spacing.md }}>Edit Question</h3>
            <MonoLabel>NLQ</MonoLabel>
            <textarea
              value={editForm.nlq}
              onChange={(e) => setEditForm(f => ({ ...f, nlq: e.target.value }))}
              rows={3}
              style={{ width: "100%", background: colors.bg, border: `1px solid ${colors.border}`, color: colors.text, padding: 8, borderRadius: 4, fontFamily: fonts.body, fontSize: 14, marginBottom: spacing.md, resize: "vertical" }}
            />
            <MonoLabel>Tone</MonoLabel>
            <select
              value={editForm.tone}
              onChange={(e) => setEditForm(f => ({ ...f, tone: e.target.value }))}
              style={{ width: "100%", background: colors.bg, border: `1px solid ${colors.border}`, color: colors.text, padding: 8, borderRadius: 4, marginBottom: spacing.md }}
            >
              <option value="casual">casual</option>
              <option value="neutral">neutral</option>
              <option value="formal">formal</option>
            </select>
            <MonoLabel>Status</MonoLabel>
            <select
              value={editForm.status}
              onChange={(e) => setEditForm(f => ({ ...f, status: e.target.value }))}
              style={{ width: "100%", background: colors.bg, border: `1px solid ${colors.border}`, color: colors.text, padding: 8, borderRadius: 4, marginBottom: spacing.md }}
            >
              <option value="active">active</option>
              <option value="monitoring">monitoring</option>
            </select>
            <MonoLabel>Notes</MonoLabel>
            <textarea
              value={editForm.notes}
              onChange={(e) => setEditForm(f => ({ ...f, notes: e.target.value }))}
              rows={2}
              style={{ width: "100%", background: colors.bg, border: `1px solid ${colors.border}`, color: colors.text, padding: 8, borderRadius: 4, fontFamily: fonts.body, fontSize: 14, marginBottom: spacing.md, resize: "vertical" }}
            />
            <div style={{ display: "flex", gap: spacing.sm, justifyContent: "flex-end" }}>
              <button onClick={() => setEditing(null)} style={rowBtn}>Cancel</button>
              <button onClick={saveEdit} style={actionBtn(colors.questions)}>Save</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

const rowBtn: React.CSSProperties = {
  padding: "3px 10px", background: "transparent",
  border: `1px solid ${colors.border}`, color: colors.textMuted,
  cursor: "pointer", borderRadius: 4, fontSize: 12,
};

function actionBtn(accent: string): React.CSSProperties {
  return {
    padding: "6px 14px", background: `${accent}18`,
    border: `1px solid ${accent}40`, color: accent,
    cursor: "pointer", borderRadius: 6, fontSize: 13, fontFamily: fonts.body,
  };
}

function toneColor(tone: string): string {
  return tone === "casual" ? "#f5a623" : tone === "formal" ? "#7c6af7" : "#888";
}
