"use client";

import type { CoverageEntry, ConfidenceLabel } from "@/lib/graphql/queries/authoring";
import { CONFIDENCE_BG, CONFIDENCE_COLOR, humanizeLabel } from "./tokens";

export type RowState = "confirmed" | "active" | "planned" | "deferred";

const DOT: Record<RowState, React.CSSProperties> = {
  confirmed: { background: "var(--color-emerald)" },
  active: {
    background: "var(--color-accent)",
    boxShadow: "0 0 0 3px var(--color-accent-glow)",
  },
  planned: { background: "transparent", border: "1px solid var(--color-text-tertiary)" },
  deferred: { background: "var(--color-amber)" },
};

export function CoverageProgress({
  confirmed,
  total,
}: {
  confirmed: number;
  total: number;
}) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div className="type-mono-value" style={{ color: "var(--color-text)" }}>
        {confirmed}/{total} confirmed
      </div>
      <div className="type-caption" style={{ marginTop: 4 }}>
        Plan adapts after each answer
      </div>
    </div>
  );
}

export function CoverageRow({
  questionId,
  confidenceLabel,
  impact,
  state,
  onSelect,
}: {
  questionId: string;
  confidenceLabel: ConfidenceLabel;
  impact?: string;
  state: RowState;
  onSelect?: () => void;
}) {
  const interactive = state === "confirmed" && Boolean(onSelect);
  const content = (
    <>
      <span
        aria-hidden="true"
        style={{
          width: 6,
          height: 6,
          borderRadius: 3,
          flexShrink: 0,
          marginRight: 8,
          ...DOT[state],
        }}
      />
      <span className="type-mono-value" style={{ color: "var(--color-text-secondary)" }}>
        {questionId}
      </span>
      <span
        className="type-badge"
        style={{
          marginLeft: "auto",
          color: CONFIDENCE_COLOR[confidenceLabel],
          background: CONFIDENCE_BG[confidenceLabel],
          padding: "3px 6px",
          borderRadius: 4,
        }}
      >
        {humanizeLabel(confidenceLabel)}
      </span>
    </>
  );

  const baseStyle: React.CSSProperties = {
    display: "flex",
    alignItems: "center",
    minHeight: 32,
    width: "100%",
    padding: "0 8px",
    borderRadius: 4,
    background: "transparent",
    border: "none",
    textAlign: "left",
  };

  return (
    <div>
      {interactive ? (
        <button
          type="button"
          onClick={onSelect}
          style={{ ...baseStyle, cursor: "pointer" }}
          aria-label={`Show the ${questionId} section in the draft`}
        >
          {content}
        </button>
      ) : (
        <div style={baseStyle}>{content}</div>
      )}
      {impact && (
        <div className="type-caption" style={{ padding: "0 8px 4px 22px" }}>
          {humanizeLabel(impact)} impact
        </div>
      )}
    </div>
  );
}

export function CoverageRail({
  coverage,
  answers,
  activeQuestionId,
  confirmed,
  total,
  onSelectQuestion,
}: {
  coverage: Record<string, CoverageEntry>;
  answers: Record<string, string>;
  activeQuestionId: string | null;
  confirmed: number;
  total: number;
  onSelectQuestion?: (questionId: string) => void;
}) {
  const entries = Object.entries(coverage);
  return (
    <aside
      className="surface-elevated"
      style={{
        width: 280,
        flexShrink: 0,
        padding: 16,
        borderRadius: 10,
        overflowY: "auto",
        display: "flex",
        flexDirection: "column",
        gap: 4,
      }}
      aria-label="Interview coverage"
    >
      <div className="type-compact-label" style={{ marginBottom: 8 }}>
        Coverage
      </div>
      <CoverageProgress confirmed={confirmed} total={total} />
      {entries.map(([questionId, entry]) => {
        const answerState = answers[questionId];
        const state: RowState =
          answerState === "confirmed"
            ? "confirmed"
            : answerState === "deferred"
              ? "deferred"
              : questionId === activeQuestionId
                ? "active"
                : "planned";
        return (
          <CoverageRow
            key={questionId}
            questionId={questionId}
            confidenceLabel={(entry.confidence_label || "missing") as ConfidenceLabel}
            impact={entry.impact}
            state={state}
            onSelect={
              onSelectQuestion ? () => onSelectQuestion(questionId) : undefined
            }
          />
        );
      })}
    </aside>
  );
}
