"use client";

import React, { useEffect, useRef, useState } from "react";
import type {
  AuthoringAction,
  CurrentQuestion,
  ResponseControl,
  Suggestion,
} from "@/lib/graphql/queries/authoring";
import { FindingsNotice, FollowUpNotice } from "./Notices";
import { SUGGESTION_BG, SUGGESTION_COLOR, humanizeLabel, middleTruncate } from "./tokens";

const ACTION_BY_VALUE: Record<string, AuthoringAction> = {
  accept: "ACCEPT",
  edit: "EDIT",
  reject: "REJECT",
  defer: "DEFER",
};

export function EvidenceNote({ evidence }: { evidence: string }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div>
      <div className="type-compact-label" style={{ marginBottom: 4 }}>
        Evidence to consider
      </div>
      <div
        className="type-body"
        style={
          expanded
            ? undefined
            : {
                display: "-webkit-box",
                WebkitLineClamp: 3,
                WebkitBoxOrient: "vertical",
                overflow: "hidden",
              }
        }
      >
        {evidence}
      </div>
      {evidence.length > 180 && (
        <button
          type="button"
          className="type-caption"
          onClick={() => setExpanded((value) => !value)}
          style={{
            background: "transparent",
            border: "none",
            padding: 0,
            marginTop: 4,
            color: "var(--color-text-secondary)",
            cursor: "pointer",
          }}
        >
          {expanded ? "Show less" : "Show more"}
        </button>
      )}
    </div>
  );
}

export function GapList({ gaps }: { gaps: string[] }) {
  if (gaps.length === 0) return null;
  return (
    <div style={{ marginTop: 8 }}>
      {gaps.map((gap, index) => (
        <div key={index} className="type-body" style={{ display: "flex", gap: 6 }}>
          <span className="type-compact-label" style={{ paddingTop: 2 }}>
            GAP
          </span>
          <span>{gap}</span>
        </div>
      ))}
    </div>
  );
}

export function SuggestionPanel({ suggestion }: { suggestion: Suggestion }) {
  const color = SUGGESTION_COLOR[suggestion.confidence] ?? "var(--color-text-tertiary)";
  const background = SUGGESTION_BG[suggestion.confidence] ?? "rgba(85, 85, 106, 0.12)";
  return (
    <section
      aria-label={`Suggested response, ${suggestion.confidence}`}
      style={{ background: "rgba(255, 255, 255, 0.02)", padding: 12, borderRadius: 4 }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <span className="type-compact-label">Suggestion</span>
        <span
          className="type-badge"
          style={{ color, background, padding: "3px 6px", borderRadius: 4 }}
        >
          {humanizeLabel(suggestion.confidence)}
        </span>
        {suggestion.rejected && (
          <span
            className="type-badge"
            style={{
              color: "var(--color-text-tertiary)",
              background: "rgba(85, 85, 106, 0.12)",
              padding: "3px 6px",
              borderRadius: 4,
            }}
          >
            Rejected
          </span>
        )}
      </div>
      {suggestion.answer ? (
        <div
          className="type-body"
          style={
            suggestion.rejected
              ? { textDecoration: "line-through", color: "var(--color-text-tertiary)" }
              : undefined
          }
        >
          {suggestion.answer}
        </div>
      ) : (
        <div style={{ fontSize: 13, color: "var(--color-text-tertiary)", lineHeight: 1.5 }}>
          No grounded response is available for this question.
        </div>
      )}
      {suggestion.sources.length > 0 && (
        <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 4 }}>
          {suggestion.sources.map((source) => (
            <div key={`${source.id}-${source.path}`} style={{ display: "flex", gap: 6 }}>
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 11,
                  fontWeight: 500,
                  color: "var(--color-text-secondary)",
                }}
              >
                {source.id}
              </span>
              <span
                title={source.path}
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 11,
                  color:
                    source.status && source.status !== "available"
                      ? "var(--color-amber)"
                      : "var(--color-text-tertiary)",
                }}
              >
                {middleTruncate(source.path)}
              </span>
            </div>
          ))}
        </div>
      )}
      <GapList gaps={suggestion.gaps} />
    </section>
  );
}

export function AnswerTextarea({
  control,
  disabled,
  value,
  onChange,
  onSubmit,
}: {
  control: ResponseControl;
  disabled: boolean;
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    node.style.height = "auto";
    node.style.height = `${Math.min(node.scrollHeight, 320)}px`;
  }, [value]);

  const labelId = `control-${control.id}`;
  return (
    <div>
      <label id={labelId} className="type-cell-label" htmlFor={control.id}>
        {control.prompt}
      </label>
      <textarea
        id={control.id}
        ref={ref}
        aria-labelledby={labelId}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
            event.preventDefault();
            onSubmit();
          }
        }}
        style={{
          display: "block",
          width: "100%",
          minHeight: 96,
          marginTop: 8,
          padding: 12,
          background: "var(--color-bg-elevated)",
          border: "1px solid var(--color-border)",
          borderRadius: 6,
          color: "var(--color-text)",
          fontFamily: "var(--font-sans)",
          fontSize: 13,
          lineHeight: 1.5,
          resize: "none",
          opacity: disabled ? 0.5 : 1,
        }}
      />
      <div className="type-caption" style={{ marginTop: 4 }}>
        Cmd/Ctrl + Enter submits
      </div>
    </div>
  );
}

export function ActionChoiceGroup({
  control,
  disabled,
  selected,
  onSelect,
}: {
  control: ResponseControl;
  disabled: boolean;
  selected: string | null;
  onSelect: (value: string) => void;
}) {
  const options = control.options ?? [];
  const groupId = `control-${control.id}`;

  const move = (delta: number) => {
    if (options.length === 0) return;
    const index = options.findIndex((option) => option.value === selected);
    const next = (index + delta + options.length) % options.length;
    onSelect(options[next].value);
  };

  return (
    <div>
      <div id={groupId} className="type-cell-label">
        {control.prompt}
      </div>
      <div
        role="radiogroup"
        aria-labelledby={groupId}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" || event.key === "ArrowRight") {
            event.preventDefault();
            move(1);
          } else if (event.key === "ArrowUp" || event.key === "ArrowLeft") {
            event.preventDefault();
            move(-1);
          } else if (/^[1-9]$/.test(event.key)) {
            const option = options[Number(event.key) - 1];
            if (option) {
              event.preventDefault();
              onSelect(option.value);
            }
          }
        }}
        style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 4 }}
      >
        {options.map((option, index) => {
          const active = option.value === selected;
          return (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={active}
              tabIndex={active || (!selected && index === 0) ? 0 : -1}
              disabled={disabled}
              onClick={() => onSelect(option.value)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                minHeight: 36,
                padding: "0 12px",
                textAlign: "left",
                borderRadius: 6,
                border: `1px solid ${active ? "var(--color-accent)" : "var(--color-border)"}`,
                background: active ? "var(--color-accent-dim)" : "transparent",
                color: "var(--color-text)",
                fontFamily: "var(--font-sans)",
                fontSize: 13,
                cursor: disabled ? "not-allowed" : "pointer",
                opacity: disabled ? 0.4 : 1,
                transition: "background 120ms ease-out, border-color 120ms ease-out",
              }}
            >
              <span
                aria-hidden="true"
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: 5,
                  flexShrink: 0,
                  border: `1px solid ${active ? "var(--color-accent)" : "var(--color-text-tertiary)"}`,
                  background: active ? "var(--color-accent)" : "transparent",
                }}
              />
              {option.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function QuestionCard({
  question,
  revision,
  submitting,
  draftText,
  onDraftTextChange,
  onAction,
  onAnswer,
}: {
  question: CurrentQuestion;
  revision: number;
  submitting: boolean;
  draftText: string;
  onDraftTextChange: (value: string) => void;
  onAction: (action: AuthoringAction) => void;
  onAnswer: (text: string) => void;
}) {
  const control = question.response_control;
  const isText = control.input_type === "textarea";
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    setSelected(null);
  }, [question.id, control.id, revision]);

  useEffect(() => {
    if (isText) onDraftTextChange(control.initial_value ?? "");
    // Prefill comes from the payload that produced this control.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [question.id, control.id, isText]);

  const findings = question.review_findings ?? [];
  const followUp = question.follow_up;
  const canSubmitText = draftText.trim().length > 0;

  return (
    <div className="surface" style={{ padding: 20, display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span className="type-mono-value" style={{ color: "var(--color-accent)" }}>
          {question.id}
        </span>
      </div>

      <div style={{ fontSize: 15, fontWeight: 500, color: "var(--color-text)", lineHeight: 1.5 }}>
        {question.prompt}
      </div>

      {question.evidence && <EvidenceNote evidence={question.evidence} />}

      {followUp?.prompt && <FollowUpNotice prompt={followUp.prompt} />}
      {!followUp?.prompt && findings.length > 0 && <FindingsNotice findings={findings} />}

      {question.suggestion && <SuggestionPanel suggestion={question.suggestion} />}

      {isText ? (
        <AnswerTextarea
          control={control}
          disabled={submitting}
          value={draftText}
          onChange={onDraftTextChange}
          onSubmit={() => canSubmitText && onAnswer(draftText)}
        />
      ) : (
        <ActionChoiceGroup
          control={control}
          disabled={submitting}
          selected={selected}
          onSelect={setSelected}
        />
      )}

      <div>
        <button
          type="button"
          disabled={submitting || (isText ? !canSubmitText : !selected)}
          onClick={() => {
            if (isText) {
              onAnswer(draftText);
              return;
            }
            if (selected) onAction(ACTION_BY_VALUE[selected] ?? "DEFER");
          }}
          className="type-badge"
          style={{
            height: 32,
            padding: "0 16px",
            borderRadius: 6,
            border: "none",
            background: "var(--color-accent)",
            color: "var(--color-bg)",
            cursor: "pointer",
            opacity: submitting || (isText ? !canSubmitText : !selected) ? 0.4 : 1,
            transition: "opacity 120ms ease-out",
          }}
        >
          {submitting ? "Saving…" : isText ? "Confirm answer" : "Continue"}
        </button>
      </div>
    </div>
  );
}
