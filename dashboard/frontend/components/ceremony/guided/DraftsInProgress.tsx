"use client";

import Link from "next/link";
import type { AuthoringSessionSummary } from "@/lib/graphql/queries/authoring";
import { humanizeLabel } from "./tokens";

/** Helper vocabulary, displayed as the helper reports it. */
const STATUS_LABEL: Record<string, string> = {
  question: "Interview in progress",
  blocked: "Blocked by a deferred answer",
  drafted: "Drafted",
  review_repair: "Draft needs repair",
  revision_conflict: "Revision conflict",
  upstream_changed: "Upstream PRD changed",
  error: "Checkpoint unreadable",
};

const STATUS_COLOR: Record<string, string> = {
  question: "var(--color-amber)",
  blocked: "var(--color-red)",
  drafted: "var(--color-emerald)",
  review_repair: "var(--color-amber)",
  revision_conflict: "var(--color-red)",
  upstream_changed: "var(--color-amber)",
  error: "var(--color-red)",
};

const FINISHED = new Set(["drafted", "published"]);

function statusColor(status: string): string {
  return STATUS_COLOR[status] ?? "var(--color-text-tertiary)";
}

function relativeTime(iso: string | null): string | null {
  if (!iso) return null;
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return null;
  const minutes = Math.round((Date.now() - then) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export function DraftRow({ session }: { session: AuthoringSessionSummary }) {
  const { featureName, featureTitle, status, revision, progress } = session;
  const unreadable = status === "error";
  const href = `/define/${featureName}/authoring/${session.artifactType || "prd"}`;
  const when = relativeTime(session.updatedAt);

  const row = (
    <>
      <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 2 }}>
        <span
          style={{
            fontFamily: "var(--font-sans)",
            fontSize: 13,
            fontWeight: 500,
            color: "var(--color-text)",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {featureTitle || featureName}
        </span>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            fontWeight: 400,
            color: "var(--color-text-tertiary)",
          }}
        >
          {featureName}
          {revision !== null && ` · rev ${revision}`}
          {when && ` · ${when}`}
        </span>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 16, flexShrink: 0 }}>
        <span
          className="type-badge"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            color: statusColor(status),
          }}
        >
          <span
            aria-hidden
            style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: statusColor(status),
            }}
          />
          {STATUS_LABEL[status] ?? humanizeLabel(status)}
        </span>
        {!unreadable && (
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              fontWeight: 500,
              color: "var(--color-text-secondary)",
              minWidth: 88,
              textAlign: "right",
            }}
          >
            {progress.confirmed}/{progress.total} confirmed
          </span>
        )}
        <span
          className="type-badge"
          style={{
            color: unreadable ? "var(--color-text-tertiary)" : "var(--color-accent)",
            minWidth: 64,
            textAlign: "right",
          }}
        >
          {unreadable ? "Unavailable" : FINISHED.has(status) ? "Open →" : "Resume →"}
        </span>
      </div>
    </>
  );

  const style: React.CSSProperties = {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 16,
    background: "var(--color-bg)",
    padding: "12px 20px",
    minHeight: 40,
    textDecoration: "none",
  };

  if (unreadable) {
    return (
      <div style={style} title={session.message}>
        {row}
      </div>
    );
  }

  return (
    <Link href={href} style={style} title={session.message}>
      {row}
    </Link>
  );
}

/**
 * Every persisted interview for this project, in the order the helper returns
 * them. Renders nothing when no interview has been started, so a project with
 * no guided drafts gains no empty furniture.
 */
export function DraftsInProgress({
  sessions,
  heading = "Guided drafts",
}: {
  sessions: AuthoringSessionSummary[];
  heading?: string;
}) {
  if (sessions.length === 0) return null;

  return (
    <section aria-label={heading}>
      <div
        style={{
          fontFamily: "var(--font-sans)",
          fontSize: 15,
          fontWeight: 600,
          color: "var(--color-text)",
          padding: "0 0 12px",
        }}
      >
        {heading} &middot; {sessions.length}
      </div>
      <div
        style={{
          display: "grid",
          gap: 1,
          background: "var(--color-border)",
          borderRadius: 10,
          overflow: "hidden",
        }}
      >
        {sessions.map((session) => (
          <DraftRow
            key={`${session.featureName}-${session.artifactType}`}
            session={session}
          />
        ))}
      </div>
    </section>
  );
}
