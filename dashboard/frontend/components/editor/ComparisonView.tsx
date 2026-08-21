"use client";

import type { SpeedAuditResult, AuditIssue } from "@/lib/graphql/queries/editor";
import { computeComparison } from "./audit-history-utils";

function severityIcon(sev: string): string {
  if (sev === "error" || sev === "critical") return "\u2715";
  if (sev === "warning" || sev === "major") return "\u26A0";
  return "\u00B7";
}

function severityColor(sev: string): string {
  if (sev === "error" || sev === "critical") return "var(--color-red)";
  if (sev === "warning" || sev === "major") return "var(--color-amber)";
  return "var(--color-text-tertiary)";
}

function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return text.slice(0, max) + "\u2026";
}

type RowVariant = "removed" | "unchanged" | "added";

function FindingRow({ issue, variant }: { issue: AuditIssue; variant: RowVariant }) {
  let messageColor: string;
  let textDecoration: string | undefined;
  let bgClass: string;

  if (variant === "removed") {
    messageColor = "rgba(68, 204, 119, 0.6)";
    textDecoration = "line-through";
    bgClass = "cv-row-removed";
  } else if (variant === "added") {
    messageColor = "rgba(239, 68, 100, 0.8)";
    textDecoration = undefined;
    bgClass = "cv-row-added";
  } else {
    messageColor = "var(--color-text-secondary)";
    textDecoration = undefined;
    bgClass = "";
  }

  return (
    <div className={`cv-row${bgClass ? ` ${bgClass}` : ""}`}>
      <span className="cv-sev" style={{ color: severityColor(issue.severity) }}>
        {severityIcon(issue.severity)}
      </span>
      <span
        className="cv-message"
        style={{ color: messageColor, textDecoration }}
      >
        {truncate(issue.message, 65)}
      </span>
    </div>
  );
}

interface SectionProps {
  label: string;
  ariaLabel: string;
  issues: AuditIssue[];
  variant: RowVariant;
}

function Section({ label, ariaLabel, issues, variant }: SectionProps) {
  return (
    <div className="cv-section" role="group" aria-label={ariaLabel}>
      <div className="cv-group-header">{label}</div>
      {issues.length === 0 ? (
        <div className="cv-none">(none)</div>
      ) : (
        issues.map((issue, i) => (
          <FindingRow key={i} issue={issue} variant={variant} />
        ))
      )}
    </div>
  );
}

interface Props {
  olderAudit: SpeedAuditResult;
  newerAudit: SpeedAuditResult;
  onExit: () => void;
}

export default function ComparisonView({ olderAudit, newerAudit, onExit }: Props) {
  const { removed, unchanged, added } = computeComparison(olderAudit, newerAudit);

  return (
    <>
      <style>{`
        .cv-container {
          overflow-y: auto;
          flex: 1;
          min-height: 0;
          animation: fvFadeIn 0.15s ease;
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        @keyframes fvFadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }
        .cv-group-header {
          padding: 10px 12px 4px;
          font-family: var(--font-mono);
          font-size: 10px;
          font-weight: 500;
          color: var(--color-text-tertiary);
        }
        .cv-none {
          padding: 4px 12px 8px;
          font-family: var(--font-sans);
          font-size: 12px;
          color: var(--color-text-tertiary);
          font-style: italic;
        }
        .cv-row {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 8px 12px;
          cursor: default;
        }
        .cv-row:hover {
          background: var(--color-bg-card-hover);
        }
        .cv-row-removed {
          background: rgba(68, 204, 119, 0.08);
        }
        .cv-row-added {
          background: rgba(239, 68, 100, 0.08);
        }
        .cv-sev {
          font-size: 11px;
          flex-shrink: 0;
          width: 14px;
          text-align: center;
          line-height: 1.45;
        }
        .cv-message {
          font-family: var(--font-sans);
          font-size: 13px;
          flex: 1;
          min-width: 0;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .cv-footer {
          padding: 12px;
          text-align: center;
          margin-top: auto;
        }
        .cv-exit-link {
          font-family: var(--font-sans);
          font-size: 11px;
          color: var(--color-text-tertiary);
          background: none;
          border: none;
          cursor: pointer;
          padding: 0;
          transition: color 0.15s ease;
        }
        .cv-exit-link:hover {
          color: var(--color-text-secondary);
        }
      `}</style>
      <div className="cv-container">
        <Section
          label="Removed"
          ariaLabel="Removed findings"
          issues={removed}
          variant="removed"
        />
        <Section
          label="Unchanged"
          ariaLabel="Unchanged findings"
          issues={unchanged}
          variant="unchanged"
        />
        <Section
          label="Added"
          ariaLabel="Added findings"
          issues={added}
          variant="added"
        />
        <div className="cv-footer">
          <button className="cv-exit-link" onClick={onExit}>
            Exit comparison
          </button>
        </div>
      </div>
    </>
  );
}
