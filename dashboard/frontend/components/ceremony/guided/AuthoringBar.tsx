"use client";

import type { AuthoringSession } from "@/lib/graphql/queries/authoring";

export type SaveState = "saved" | "saving" | "conflict";

const SAVE_STYLE: Record<SaveState, { label: string; color: string; background: string }> = {
  saved: { label: "Saved", color: "var(--color-emerald)", background: "rgba(68, 204, 119, 0.12)" },
  saving: { label: "Saving…", color: "var(--color-amber)", background: "rgba(240, 178, 50, 0.12)" },
  conflict: { label: "Conflict", color: "var(--color-red)", background: "rgba(239, 68, 100, 0.12)" },
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
}: {
  session: AuthoringSession;
  saveState: SaveState;
}) {
  const title = session.featureTitle || session.featureName || "";
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
          PRD
        </span>
        {session.revision !== null && (
          <span className="type-mono-value" style={{ color: "var(--color-text-secondary)" }}>
            rev {session.revision}
          </span>
        )}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <span
          className="type-caption"
          role="status"
          aria-live="polite"
        >
          {session.progress.confirmed}/{session.progress.total} confirmed
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
        Someone else answered this interview. This tab holds revision {heldRevision}
        {currentRevision !== null ? `, current revision is ${currentRevision}` : ""}. Your
        typed answer is kept.
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
