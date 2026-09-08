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

export function AnswerChoiceGroup({
  control,
  disabled,
  selected,
  onSelect,
}: {
  control: ResponseControl;
  disabled: boolean;
  selected: string[];
  onSelect: (value: string) => void;
}) {
  const multiple = control.input_type === "multi_select";
  const options = [
    ...(control.options ?? []),
    ...(control.allow_other
      ? [{ value: "__other__", label: "Other — write my own answer", description: null }]
      : []),
  ];
  const groupId = `control-${control.id}`;
  return (
    <div>
      <div id={groupId} className="type-cell-label">{control.prompt}</div>
      {multiple && (
        <div className="type-caption" style={{ marginTop: 4 }}>
          Select every statement that should apply. Suggested choices are proposed from
          the feature context; review each one before submitting.
        </div>
      )}
      <div
        role={multiple ? "group" : "radiogroup"}
        aria-labelledby={groupId}
        style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 6 }}
      >
        {options.map((option) => {
          const active = selected.includes(option.value);
          return (
            <button
              key={option.value}
              type="button"
              role={multiple ? "checkbox" : "radio"}
              aria-checked={active}
              disabled={disabled}
              onClick={() => onSelect(option.value)}
              style={{
                display: "flex",
                alignItems: "flex-start",
                gap: 10,
                padding: "10px 12px",
                textAlign: "left",
                borderRadius: 6,
                border: `1px solid ${active ? "var(--color-accent)" : "var(--color-border)"}`,
                background: active ? "var(--color-accent-dim)" : "transparent",
                color: "var(--color-text)",
                cursor: disabled ? "not-allowed" : "pointer",
                opacity: disabled ? 0.4 : 1,
              }}
            >
              <span
                aria-hidden="true"
                style={{
                  width: 12,
                  height: 12,
                  marginTop: 2,
                  borderRadius: multiple ? 2 : 6,
                  flexShrink: 0,
                  border: `1px solid ${active ? "var(--color-accent)" : "var(--color-text-tertiary)"}`,
                  background: active ? "var(--color-accent)" : "transparent",
                }}
              />
              <span style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                <span style={{ fontSize: 13, fontWeight: 500 }}>
                  {option.label}
                  {"recommended" in option && option.recommended && (
                    <span className="type-compact-label" style={{ marginLeft: 8, color: "var(--color-accent)" }}>
                      Suggested
                    </span>
                  )}
                </span>
                {option.description && (
                  <span className="type-caption">{option.description}</span>
                )}
              </span>
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
  onDirtyChange,
  position,
  total,
  prepared = false,
  preparedAnswer,
  answerButtonLabel,
  submittingButtonLabel,
  onPrevious,
  onNext,
}: {
  question: CurrentQuestion;
  revision: number;
  submitting: boolean;
  draftText: string;
  onDraftTextChange: (value: string) => void;
  onAction: (action: AuthoringAction) => void;
  onAnswer: (text: string) => void;
  onDirtyChange?: (dirty: boolean) => void;
  position?: number;
  total?: number;
  prepared?: boolean;
  preparedAnswer?: string;
  answerButtonLabel?: string;
  submittingButtonLabel?: string;
  onPrevious?: () => void;
  onNext?: () => void;
}) {
  const control = question.response_control;
  const isText = control.input_type === "textarea";
  const isAnswerChoice =
    control.submit_action === "answer" &&
    (control.input_type === "single_select" || control.input_type === "multi_select");
  const [selected, setSelected] = useState<string | null>(null);
  const [selectedAnswers, setSelectedAnswers] = useState<string[]>([]);
  const [otherAnswer, setOtherAnswer] = useState("");

  useEffect(() => {
    setSelected(null);
    setSelectedAnswers([]);
    setOtherAnswer("");
    if (!isAnswerChoice || !preparedAnswer) return;
    const optionValues = (control.options ?? []).map((option) => option.value);
    if (control.input_type === "single_select") {
      if (optionValues.includes(preparedAnswer)) {
        setSelectedAnswers([preparedAnswer]);
      } else {
        setSelectedAnswers(["__other__"]);
        setOtherAnswer(preparedAnswer);
      }
      return;
    }
    const submittedValues = preparedAnswer.split("\n").filter(Boolean);
    const known = submittedValues.filter((value) => optionValues.includes(value));
    const other = submittedValues.filter((value) => !optionValues.includes(value));
    setSelectedAnswers([...known, ...(other.length ? ["__other__"] : [])]);
    setOtherAnswer(other.join("\n"));
  }, [question.id, control.id, isAnswerChoice, preparedAnswer]);

  useEffect(() => {
    if (isText) onDraftTextChange(preparedAnswer ?? control.initial_value ?? "");
    // Prefill comes from the payload that produced this control.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [question.id, control.id, isText, preparedAnswer]);

  const findings = question.review_findings ?? [];
  const followUp = question.follow_up;
  const canSubmitText = draftText.trim().length > 0;
  const otherSelected = selectedAnswers.includes("__other__");
  const canSubmitChoice =
    selectedAnswers.length > 0 && (!otherSelected || otherAnswer.trim().length > 0);
  const choiceAnswer = () => selectedAnswers
    .filter((value) => value !== "__other__")
    .concat(otherSelected ? [otherAnswer.trim()] : [])
    .join("\n");

  return (
    <div
      className="surface"
      style={{ padding: 20, display: "flex", flexDirection: "column", gap: 16 }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
        }}
      >
        <div className="type-compact-label">
          {position && total ? "Question" : "Let's clarify one thing"}
          {prepared ? " · Answer ready" : ""}
        </div>
        {position && total && total > 1 && (
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <button
              type="button"
              aria-label="Previous question"
              disabled={submitting || !onPrevious}
              onClick={onPrevious}
              className="type-section-title"
              style={{
                border: "none",
                background: "transparent",
                color: "var(--color-text-secondary)",
                cursor: onPrevious ? "pointer" : "not-allowed",
                opacity: onPrevious ? 1 : 0.35,
                padding: "0 4px",
              }}
            >
              ‹
            </button>
            <span className="type-mono-value" aria-live="polite">
              {position}/{total}
            </span>
            <button
              type="button"
              aria-label="Next question"
              disabled={submitting || !onNext}
              onClick={onNext}
              className="type-section-title"
              style={{
                border: "none",
                background: "transparent",
                color: "var(--color-text-secondary)",
                cursor: onNext ? "pointer" : "not-allowed",
                opacity: onNext ? 1 : 0.35,
                padding: "0 4px",
              }}
            >
              ›
            </button>
          </div>
        )}
      </div>

      <div style={{ fontSize: 15, fontWeight: 500, color: "var(--color-text)", lineHeight: 1.5 }}>
        {question.prompt}
      </div>

      {question.evidence && <EvidenceNote evidence={question.evidence} />}

      {followUp?.prompt && <FollowUpNotice prompt={followUp.prompt} />}
      {!followUp?.prompt && findings.length > 0 && <FindingsNotice findings={findings} />}

      {question.suggestion?.answer && <SuggestionPanel suggestion={question.suggestion} />}

      {isText ? (
        <AnswerTextarea
          control={control}
          disabled={submitting}
          value={draftText}
          onChange={(value) => {
            onDirtyChange?.(Boolean(value.trim()));
            onDraftTextChange(value);
          }}
          onSubmit={() => canSubmitText && onAnswer(draftText)}
        />
      ) : isAnswerChoice ? (
        <>
          <AnswerChoiceGroup
            control={control}
            disabled={submitting}
            selected={selectedAnswers}
            onSelect={(value) => {
              onDirtyChange?.(true);
              if (control.input_type === "multi_select") {
                setSelectedAnswers((current) =>
                  current.includes(value)
                    ? current.filter((item) => item !== value)
                    : [...current, value],
                );
              } else {
                setSelectedAnswers([value]);
              }
            }}
          />
          {otherSelected && (
            <AnswerTextarea
              control={{ ...control, id: `${control.id}-other`, prompt: "Your answer" }}
              disabled={submitting}
              value={otherAnswer}
              onChange={(value) => {
                onDirtyChange?.(true);
                setOtherAnswer(value);
              }}
              onSubmit={() => canSubmitChoice && onAnswer(choiceAnswer())}
            />
          )}
        </>
      ) : (
        <ActionChoiceGroup
          control={control}
          disabled={submitting}
          selected={selected}
          onSelect={(value) => {
            onDirtyChange?.(true);
            setSelected(value);
          }}
        />
      )}

      <div>
        <button
          type="button"
          disabled={
            submitting ||
            (isText ? !canSubmitText : isAnswerChoice ? !canSubmitChoice : !selected)
          }
          onClick={() => {
            if (isText) {
              onAnswer(draftText);
              return;
            }
            if (isAnswerChoice) {
              onAnswer(choiceAnswer());
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
            opacity:
              submitting ||
              (isText ? !canSubmitText : isAnswerChoice ? !canSubmitChoice : !selected)
                ? 0.4
                : 1,
            transition: "opacity 120ms ease-out",
          }}
        >
          {submitting
            ? submittingButtonLabel ?? "Saving…"
            : isText || isAnswerChoice
              ? answerButtonLabel ?? (prepared ? "Update answer" : "Save answer")
              : "Continue"}
        </button>
      </div>
    </div>
  );
}

export function QuestionBatch({
  questions,
  revision,
  submitting,
  onSubmit,
  artifactLabel = "PRD",
  onDirtyChange,
}: {
  questions: CurrentQuestion[];
  revision: number;
  submitting: boolean;
  onSubmit: (answer: { question_id: string; answer: string }) => void;
  artifactLabel?: string;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const questionKey = questions.map((question) => question.id).join(":");

  useEffect(() => {
    setDrafts(Object.fromEntries(
      questions.map((question) => [
        question.id,
        question.response_control.initial_value ?? "",
      ]),
    ));
    onDirtyChange?.(false);
    // Reset only when the persisted batch changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [questionKey]);

  // Only the current persisted question is rendered here. After it is saved,
  // the server advances the checkpoint and the route renders the next
  // question from that checkpoint. Keeping progression server-driven prevents
  // a reload or surface switch from losing answers held only in React state.
  const currentQuestion = questions[0];
  const isLastQuestion = questions.length === 1;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="surface" role="status" style={{ padding: 16 }}>
        <div className="type-compact-label">Interview planned once</div>
        <div className="type-body" style={{ marginTop: 6 }}>
          These {questions.length} questions were identified together from your feature
          description and the {artifactLabel} template. Answer one at a time; Continue moves to the
          next prepared question without another planning wait.
        </div>
      </div>
      {currentQuestion && (
        <QuestionCard
          key={currentQuestion.id}
          question={currentQuestion}
          revision={revision}
          submitting={submitting}
          draftText={drafts[currentQuestion.id] ?? ""}
          onDraftTextChange={(value) =>
            setDrafts((current) => ({
              ...current,
              [currentQuestion.id]: value,
            }))
          }
          onDirtyChange={onDirtyChange}
          onAction={() => undefined}
          onAnswer={(answer) => {
            onDirtyChange?.(true);
            onSubmit({ question_id: currentQuestion.id, answer });
          }}
          position={1}
          total={questions.length}
          prepared={false}
          answerButtonLabel={
            isLastQuestion
              ? `Generate ${artifactLabel}`
              : "Save & continue"
          }
          submittingButtonLabel={isLastQuestion ? `Generating ${artifactLabel}…` : "Saving…"}
        />
      )}
    </div>
  );
}
