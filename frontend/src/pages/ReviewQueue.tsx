import { useState } from "react";
import { useReviewQueue } from "../hooks/useReviewQueue";
import Card from "../components/ui/Card";
import MonoLabel from "../components/ui/MonoLabel";
import DotRating from "../components/ui/DotRating";
import { colors, fonts, spacing } from "../theme";

export default function ReviewQueue() {
  const { items, stats, loading, submit } = useReviewQueue({ pending_only: "true" });
  const [reviewerName, setReviewerName] = useState("");
  const [notes, setNotes] = useState<Record<string, string>>({});

  const handleDecision = async (id: string, decision: string) => {
    await submit(id, decision, reviewerName || undefined, notes[id] || undefined);
  };

  return (
    <div>
      <h1 style={{ fontFamily: fonts.heading, fontSize: 28, marginBottom: spacing.md }}>Review Queue</h1>

      {/* Stats strip */}
      <div style={{ display: "flex", gap: spacing.lg, marginBottom: spacing.xl }}>
        {[
          { label: "Pending", val: stats.pending, color: colors.review },
          { label: "Confirmed Pass", val: stats.confirmed_pass, color: colors.passed },
          { label: "Overridden Fail", val: stats.override_fail, color: colors.failed },
        ].map(({ label, val, color }) => (
          <div key={label}>
            <MonoLabel>{label}</MonoLabel>
            <span style={{ fontFamily: fonts.heading, fontSize: 24, color }}>{val}</span>
          </div>
        ))}
      </div>

      {/* Reviewer name */}
      <div style={{ marginBottom: spacing.lg }}>
        <MonoLabel>Your Name (optional)</MonoLabel>
        <input
          value={reviewerName}
          onChange={(e) => setReviewerName(e.target.value)}
          placeholder="Reviewer name..."
          style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.text, padding: "6px 10px", borderRadius: 4, fontSize: 14, width: 240 }}
        />
      </div>

      {loading ? (
        <p style={{ color: colors.textMuted }}>Loading...</p>
      ) : items.length === 0 ? (
        <p style={{ color: colors.textMuted }}>No pending items. 🎉</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: spacing.md }}>
          {items.map((item) => (
            <Card key={item.id} accentColor={colors.review}>
              <div style={{ marginBottom: spacing.sm }}>
                <div style={{ fontSize: 14, fontWeight: 500, marginBottom: 6 }}>{item.nlq_snapshot}</div>
                <DotRating score={item.judge_confidence} accentColor={colors.review} />
              </div>

              {item.judge_reasoning && (
                <div style={{ marginBottom: spacing.sm }}>
                  <MonoLabel>Judge Reasoning</MonoLabel>
                  <p style={{ fontSize: 13, color: colors.textMuted, lineHeight: 1.6 }}>{item.judge_reasoning}</p>
                </div>
              )}

              <MonoLabel>Review Notes</MonoLabel>
              <textarea
                value={notes[item.id] || ""}
                onChange={(e) => setNotes(n => ({ ...n, [item.id]: e.target.value }))}
                rows={2}
                placeholder="Optional notes..."
                style={{ width: "100%", background: colors.bg, border: `1px solid ${colors.border}`, color: colors.text, padding: 8, borderRadius: 4, fontSize: 13, marginBottom: spacing.sm, resize: "vertical" }}
              />

              <div style={{ display: "flex", gap: spacing.sm }}>
                <button
                  onClick={() => handleDecision(item.id, "confirmed_pass")}
                  style={{ ...decisionBtn(colors.passed) }}
                >
                  ✓ Confirm Pass
                </button>
                <button
                  onClick={() => handleDecision(item.id, "override_fail")}
                  style={{ ...decisionBtn(colors.failed) }}
                >
                  ✗ Override Fail
                </button>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

function decisionBtn(accent: string): React.CSSProperties {
  return {
    padding: "6px 16px", background: `${accent}18`,
    border: `1px solid ${accent}50`, color: accent,
    cursor: "pointer", borderRadius: 6, fontSize: 13, fontWeight: 600,
  };
}
