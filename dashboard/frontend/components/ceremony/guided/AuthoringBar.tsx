"use client";

import type { AuthoringSession } from "@/lib/graphql/queries/authoring";

export type SaveState = "saved" | "unsaved" | "saving" | "conflict" | "error";
export type AuthoringView = "focused" | "coverage";

const SAVE_STYLE: Record<SaveState, { label: string; color: string; background: string }> = {
  saved: { label: "Saved", color: "var(--color-emerald)", background: "rgba(68, 204, 119, 0.12)" },
  unsaved: { label: "Unsaved", color: "var(--color-amber)", background: "rgba(240, 178, 50, 0.12)" },
  saving: { label: "Saving…", color: "var(--color-amber)", background: "rgba(240, 178, 50, 0.12)" },
  conflict: { label: "Conflict", color: "var(--color-red)", background: "rgba(239, 68, 100, 0.12)" },
  error: { label: "Not saved", color: "var(--color-red)", background: "rgba(239, 68, 100, 0.12)" },
};

export function SaveStateChip({ state }: { state: SaveState }) {
  const { label, color, background } = SAVE_STYLE[state];
  return (
    <span
      className="type-badge"
      role="status"
      aria-live="polite"
      style={{ color, background, padding: "3px 8px", borderRadius: 4 }}
    >
      {label}
    </span>
  );
}

export function AuthoringBar({
  session,
  saveState,
  view = "focused",
  onViewChange,
}: {
  session: AuthoringSession;
  saveState: SaveState;
  view?: AuthoringView;
  onViewChange?: (view: AuthoringView) => void;
}) {
  const hasDerivedPrdTitle =
    session.artifactType !== "prd" ||
    Boolean(session.intake?.feature_title && session.featureTitle);
  const title = hasDerivedPrdTitle
    ? session.featureTitle || session.featureName || ""
    : saveState === "error" ||
        (session.planning?.mode === "fallback" &&
          session.planning?.planner_version === "model-prd-v5")
      ? "Title unavailable"
      : "Deriving title…";
  const artifactLabel = session.artifactType === "design" ? "Design" : session.artifactType === "rfc" ? "Technical RFC" : "PRD";
  const ready = ["drafted", "published"].includes(session.status);
  const repairing = session.status === "review_repair" && session.draftAvailable;
  return (
    <div
      className="surface-elevated"
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 12,
        height: 40,
        padding: "0 24px",
        borderRadius: 0,
        borderLeft: "none",
        borderRight: "none",
        borderTop: "none",
        flexShrink: 0,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0 }}>
        <span
          className="type-section-header"
          title={title}
          style={{
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            maxWidth: 420,
          }}
        >
          {title}
        </span>
        <span
          className="type-badge"
          style={{
            color: "var(--color-text-secondary)",
            background: "rgba(255, 255, 255, 0.04)",
            padding: "3px 8px",
            borderRadius: 4,
          }}
        >
          {artifactLabel}
        </span>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        {onViewChange && (
          <div
            role="group"
            aria-label={`${artifactLabel} authoring view`}
            style={{
              display: "flex",
              padding: 2,
              border: "1px solid var(--color-border)",
              borderRadius: 6,
              background: "var(--color-bg)",
            }}
          >
            {(["focused", "coverage"] as const).map((option) => (
              <button
                key={option}
                type="button"
                aria-pressed={view === option}
                onClick={() => onViewChange(option)}
                style={{
                  border: "none",
                  borderRadius: 4,
                  padding: "3px 8px",
                  background:
                    view === option ? "var(--color-bg-card-hover)" : "transparent",
                  color:
                    view === option ? "var(--color-text)" : "var(--color-text-tertiary)",
                  fontFamily: "var(--font-sans)",
                  fontSize: 11,
                  cursor: "pointer",
                }}
              >
                {option === "focused" ? "Focused draft" : "Full coverage"}
              </button>
            ))}
          </div>
        )}
        <span
          className="type-caption"
          role="status"
          aria-live="polite"
        >
          {view === "focused"
            ? ready
              ? `V1 ready · ${session.progress.confirmed} confirmed input${session.progress.confirmed === 1 ? "" : "s"}`
              : repairing
                ? "Draft needs repair before V1"
              : "Interview in progress"
            : `${session.progress.confirmed}/${session.progress.total} confirmed`}
        </span>
        <SaveStateChip state={saveState} />
      </div>
    </div>
  );
}

export function ConflictBanner({
  heldRevision,
  currentRevision,
  onReload,
}: {
  heldRevision: number;
  currentRevision: number | null;
  onReload: () => void;
}) {
  return (
    <div
      role="alert"
      aria-live="assertive"
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 12,
        padding: "12px 24px",
        background: "rgba(240, 178, 50, 0.08)",
        border: "1px solid var(--color-amber)",
        borderLeft: "none",
        borderRight: "none",
        flexShrink: 0,
      }}
    >
      <span className="type-body" style={{ color: "var(--color-amber)" }}>
        This draft changed before your update finished. This tab holds revision {heldRevision}
        {currentRevision !== null ? `, current revision is ${currentRevision}` : ""}. Your
        typed answer is kept; reload to use the latest draft.
      </span>
      <button
        type="button"
        onClick={onReload}
        className="type-badge"
        style={{
          background: "transparent",
          color: "var(--color-text-secondary)",
          border: "1px solid var(--color-border)",
          borderRadius: 4,
          padding: "6px 12px",
          cursor: "pointer",
        }}
      >
        Reload
      </button>
    </div>
  );
}
