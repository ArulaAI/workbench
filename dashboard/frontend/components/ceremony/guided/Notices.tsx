"use client";

import type { AuthoringSession } from "@/lib/graphql/queries/authoring";

function Notice({
  tone,
  role,
  live,
  children,
}: {
  tone: "info" | "warn";
  role: "note" | "alert";
  live: "polite" | "assertive";
  children: React.ReactNode;
}) {
  const color = tone === "info" ? "var(--color-blue)" : "var(--color-amber)";
  const background =
    tone === "info" ? "rgba(75, 166, 238, 0.08)" : "rgba(240, 178, 50, 0.08)";
  return (
    <div
      role={role}
      aria-live={live}
      style={{
        background,
        borderLeft: `2px solid ${color}`,
        padding: 12,
        borderRadius: 4,
      }}
    >
      {children}
    </div>
  );
}

export function FollowUpNotice({ prompt }: { prompt: string }) {
  return (
    <Notice tone="info" role="note" live="polite">
      <div className="type-compact-label" style={{ marginBottom: 4 }}>
        Targeted follow-up
      </div>
      <div style={{ fontSize: 13, fontWeight: 500, color: "var(--color-text)" }}>
        {prompt}
      </div>
    </Notice>
  );
}

export function FindingsNotice({
  findings,
}: {
  findings: { message: string; question_id: string }[];
}) {
  return (
    <Notice tone="warn" role="alert" live="assertive">
      <div className="type-compact-label" style={{ marginBottom: 4 }}>
        Self-review
      </div>
      {findings.map((finding, index) => (
        <div
          key={`${finding.question_id}-${index}`}
          className="type-body"
          style={{ color: "var(--color-amber)" }}
        >
          {finding.message}
        </div>
      ))}
    </Notice>
  );
}

export function BlockingNotice({ message, deferred }: { message: string; deferred: string[] }) {
  return (
    <Notice tone="warn" role="note" live="polite">
      <div className="type-body" style={{ color: "var(--color-amber)" }}>
        {message}
      </div>
      {deferred.length > 0 && (
        <div className="type-mono-value" style={{ marginTop: 8, color: "var(--color-amber)" }}>
          Deferred: {deferred.join(", ")}
        </div>
      )}
    </Notice>
  );
}

export function SelfReviewSummary({
  session,
  onEditQuestion,
  pendingCommentCount = 0,
  regenerating = false,
  onRegenerate,
  artifactLabel = "PRD",
}: {
  session: AuthoringSession;
  onEditQuestion: (questionId: string) => void;
  artifactLabel?: string;
  pendingCommentCount?: number;
  regenerating?: boolean;
  onRegenerate?: () => void;
}) {
  const findings = session.selfReview?.findings ?? [];
  const passed = session.status === "drafted" || session.status === "published";
  return (
    <div className="surface" style={{ padding: 20 }}>
      <div className="type-section-title" style={{ marginBottom: 8 }}>
        {session.status === "published"
          ? `${artifactLabel} published`
          : passed
            ? `${artifactLabel} drafted`
            : session.status === "review_repair"
              ? `${artifactLabel} needs repair`
              : `${artifactLabel} interview needs more information`}
      </div>
      <div
        className="type-body"
        style={{ color: passed ? "var(--color-emerald)" : "var(--color-amber)" }}
      >
        {session.message}
      </div>
      {findings.length > 0 && (
        <ul style={{ listStyle: "none", padding: 0, margin: "16px 0 0 0" }}>
          {findings.map((finding, index) => (
            <li
              key={`${finding.question_id ?? "document"}-${index}`}
              style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 8 }}
            >
              {finding.question_id && (
                <span className="type-mono-value" style={{ color: "var(--color-text-secondary)" }}>
                  {finding.question_id}
                </span>
              )}
              <span className="type-body" style={{ flex: 1 }}>
                {finding.message}
              </span>
              {finding.question_id ? (
                <button
                  type="button"
                  className="type-caption"
                  onClick={() => onEditQuestion(finding.question_id as string)}
                  style={{
                    background: "transparent",
                    border: "none",
                    color: "var(--color-text-secondary)",
                    cursor: "pointer",
                    fontWeight: 500,
                  }}
                >
                  Edit answer
                </button>
              ) : (
                <span className="type-caption">Fix in editor</span>
              )}
            </li>
          ))}
        </ul>
      )}
      {session.artifactPath && (
        <div style={{ marginTop: 16, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
          <div className="type-caption">{session.artifactPath}</div>
          {pendingCommentCount > 0 && onRegenerate && (
            <button
              type="button"
              className="type-badge"
              disabled={regenerating}
              onClick={onRegenerate}
              style={{ height: 32, padding: "0 16px", border: "1px solid var(--color-accent)", borderRadius: 6, background: "var(--color-accent-dim)", color: "var(--color-accent)", cursor: regenerating ? "not-allowed" : "pointer" }}
            >
              {regenerating ? "Regenerating…" : `Regenerate with ${pendingCommentCount} comment${pendingCommentCount === 1 ? "" : "s"}`}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export function HelperUnavailable({
  message,
  helperPath,
  interpreter,
  onRetry,
}: {
  message: string;
  helperPath: string | null;
  interpreter: string | null;
  onRetry: () => void;
}) {
  return (
    <div className="surface" style={{ padding: 20 }}>
      <div className="type-section-title" style={{ marginBottom: 8 }}>
        The interview helper could not run
      </div>
      <div className="type-body" style={{ color: "var(--color-red)" }}>
        {message}
      </div>
      <div className="type-caption" style={{ marginTop: 16, fontFamily: "var(--font-mono)" }}>
        helper: {helperPath ?? "unresolved"}
        <br />
        interpreter: {interpreter ?? "unresolved"}
      </div>
      <button
        type="button"
        className="type-badge"
        onClick={onRetry}
        style={{
          marginTop: 16,
          background: "transparent",
          color: "var(--color-text-secondary)",
          border: "1px solid var(--color-border)",
          borderRadius: 4,
          padding: "6px 12px",
          cursor: "pointer",
        }}
      >
        Retry
      </button>
    </div>
  );
}
