"use client";

import { useEffect, useState } from "react";
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  MessageCircle,
} from "lucide-react";
import type { InterviewAnswer } from "@/lib/graphql/queries/authoring";

export function AnswerReviewCarousel({
  answers,
  onEditAnswer,
}: {
  answers: InterviewAnswer[];
  onEditAnswer?: (questionId: string, answer: string) => void;
}) {
  const [expanded, setExpanded] = useState(true);
  const [currentIndex, setCurrentIndex] = useState(0);

  useEffect(() => {
    setCurrentIndex((index) => Math.min(index, Math.max(answers.length - 1, 0)));
  }, [answers.length]);

  if (answers.length === 0) return null;

  const current = answers[currentIndex];
  const answer = current.answer?.trim() || "Skipped";

  return (
    <section aria-label="Questions and answers">
      <button
        type="button"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "4px 0",
          border: 0,
          background: "transparent",
          color: "var(--color-text)",
          cursor: "pointer",
          textAlign: "left",
        }}
      >
        <MessageCircle aria-hidden="true" size={18} />
        <span className="type-section-title" style={{ flex: 1 }}>
          Questions
        </span>
        <span
          aria-hidden="true"
          style={{
            width: 8,
            height: 8,
            borderRadius: "50%",
            background: "var(--color-emerald)",
          }}
        />
        {expanded ? (
          <ChevronUp aria-hidden="true" size={16} />
        ) : (
          <ChevronDown aria-hidden="true" size={16} />
        )}
      </button>

      {expanded && (
        <div style={{ marginTop: 12 }}>
          <div className="type-compact-label" style={{ marginBottom: 10 }}>
            Your answers
          </div>
          <div
            className="surface"
            style={{
              padding: "14px 16px",
              display: "flex",
              flexDirection: "column",
              gap: 8,
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 12,
              }}
            >
              <span className="type-compact-label">{current.id}</span>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                {onEditAnswer && (
                  <button
                    type="button"
                    className="type-caption"
                    onClick={() =>
                      onEditAnswer(current.coverage_id || current.id, current.answer ?? "")
                    }
                    style={{
                      border: 0,
                      padding: "2px 4px",
                      background: "transparent",
                      color: "var(--color-text-secondary)",
                      cursor: "pointer",
                    }}
                  >
                    Edit
                  </button>
                )}
                <button
                  type="button"
                  aria-label="Previous answer"
                  disabled={currentIndex === 0}
                  onClick={() => setCurrentIndex((index) => index - 1)}
                  style={{
                    display: "inline-flex",
                    border: 0,
                    padding: 2,
                    background: "transparent",
                    color: "var(--color-text-secondary)",
                    cursor: currentIndex === 0 ? "not-allowed" : "pointer",
                    opacity: currentIndex === 0 ? 0.35 : 1,
                  }}
                >
                  <ChevronLeft aria-hidden="true" size={18} />
                </button>
                <span className="type-mono-value" aria-live="polite">
                  {currentIndex + 1}/{answers.length}
                </span>
                <button
                  type="button"
                  aria-label="Next answer"
                  disabled={currentIndex === answers.length - 1}
                  onClick={() => setCurrentIndex((index) => index + 1)}
                  style={{
                    display: "inline-flex",
                    border: 0,
                    padding: 2,
                    background: "transparent",
                    color: "var(--color-text-secondary)",
                    cursor:
                      currentIndex === answers.length - 1 ? "not-allowed" : "pointer",
                    opacity: currentIndex === answers.length - 1 ? 0.35 : 1,
                  }}
                >
                  <ChevronRight aria-hidden="true" size={18} />
                </button>
              </div>
            </div>
            <div
              style={{
                fontSize: 14,
                fontWeight: 500,
                color: "var(--color-text)",
                lineHeight: 1.45,
              }}
            >
              {current.prompt}
            </div>
            <div className="type-body" style={{ color: "var(--color-text)" }}>
              {answer}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
