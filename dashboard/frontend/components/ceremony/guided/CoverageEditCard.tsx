"use client";

import { useEffect, useRef, useState } from "react";

export function CoverageEditCard({
  questionId,
  initialAnswer,
  submitting,
  onCancel,
  onSubmit,
}: {
  questionId: string;
  initialAnswer?: string | null;
  submitting: boolean;
  onCancel: () => void;
  onSubmit: (answer: string) => void;
}) {
  const [answer, setAnswer] = useState(initialAnswer ?? "");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    setAnswer(initialAnswer ?? "");
    textareaRef.current?.focus();
  }, [initialAnswer, questionId]);

  return (
    <form
      className="surface"
      style={{ padding: 20 }}
      onSubmit={(event) => {
        event.preventDefault();
        if (answer.trim().length < 3 || submitting) return;
        onSubmit(answer.trim());
      }}
    >
      <div className="type-section-title">Revise {questionId}</div>
      <div className="type-body" style={{ marginTop: 8 }}>
        Replace the interview answer behind the selected PRD section. The document will
        regenerate after you confirm the new answer.
      </div>
      <label
        className="type-cell-label"
        htmlFor={`coverage-edit-${questionId}`}
        style={{ display: "block", marginTop: 16 }}
      >
        Replacement answer
      </label>
      <textarea
        ref={textareaRef}
        id={`coverage-edit-${questionId}`}
        value={answer}
        disabled={submitting}
        onChange={(event) => setAnswer(event.target.value)}
        style={{
          display: "block",
          width: "100%",
          minHeight: 120,
          marginTop: 8,
          padding: 12,
          background: "var(--color-bg-elevated)",
          border: "1px solid var(--color-border)",
          borderRadius: 6,
          color: "var(--color-text)",
          fontFamily: "var(--font-sans)",
          fontSize: 13,
          lineHeight: 1.5,
          resize: "vertical",
        }}
      />
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 16 }}>
        <button
          type="button"
          className="type-badge"
          disabled={submitting}
          onClick={onCancel}
          style={{
            height: 32,
            padding: "0 16px",
            borderRadius: 6,
            border: "1px solid var(--color-border)",
            background: "transparent",
            color: "var(--color-text-secondary)",
            cursor: submitting ? "not-allowed" : "pointer",
          }}
        >
          Cancel
        </button>
        <button
          type="submit"
          className="type-badge"
          disabled={answer.trim().length < 3 || submitting}
          style={{
            height: 32,
            padding: "0 16px",
            borderRadius: 6,
            border: "none",
            background: "var(--color-accent)",
            color: "var(--color-bg)",
            cursor: answer.trim().length < 3 || submitting ? "not-allowed" : "pointer",
            opacity: answer.trim().length < 3 || submitting ? 0.4 : 1,
          }}
        >
          {submitting ? "Updating…" : "Update PRD"}
        </button>
      </div>
    </form>
  );
}
