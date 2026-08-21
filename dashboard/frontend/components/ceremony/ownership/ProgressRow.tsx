"use client";

import { Check, AlertCircle, Clock } from "lucide-react";

/**
 * ProgressRow — one spec per row in the ProgressOverview.
 *
 * Row data is the normalized ProgressRowData shape that CeremonyLayout
 * composes from ceremonyClaims + drafts + suggestions + commit state.
 * Clicking the row activates that spec's tab in the editor (not a
 * navigation — a tab swap).
 */

export type ProgressRowStatus =
  | "drafting"
  | "committed"
  | "ratified"
  | "rejected";

export type ClaimantStatus = "active" | "stale" | "released" | "unclaimed";

export type ValidationSummary = "pass" | "warn" | "fail" | "pending";

export interface ProgressRowData {
  specType: string;
  claimant: string | null;
  claimantStatus: ClaimantStatus;
  validation: ValidationSummary;
  validationWarnings: number;
  suggestionsOpen: number;
  status: ProgressRowStatus;
}

interface ProgressRowProps {
  row: ProgressRowData;
  isActiveTab: boolean;
  onClick: () => void;
}

function formatSpecType(specType: string): string {
  if (specType === "prd") return "PRD";
  if (specType === "design") return "Design";
  if (specType === "rfc") return "RFC";
  if (specType.startsWith("rfc-")) {
    const slug = specType.slice(4);
    return `RFC: ${slug}`;
  }
  return specType.toUpperCase();
}

function claimantColor(status: ClaimantStatus): string {
  switch (status) {
    case "active":
      return "var(--color-text-secondary)";
    case "stale":
      return "var(--color-amber)";
    case "released":
      return "var(--color-text-tertiary)";
    case "unclaimed":
      return "var(--color-text-tertiary)";
  }
}

const STATUS_LABEL: Record<ProgressRowStatus, string> = {
  drafting: "drafting",
  committed: "committed",
  ratified: "ratified",
  rejected: "rejected",
};

export function ProgressRow({
  row,
  isActiveTab,
  onClick,
}: ProgressRowProps) {
  const claimantDisplay =
    row.claimant === null
      ? "unclaimed"
      : row.claimant.length > 18
        ? row.claimant.slice(0, 17) + "…"
        : row.claimant;
  const claimantItalic = row.claimant === null;

  return (
    <button
      className="progress-row"
      data-active={isActiveTab ? "true" : "false"}
      data-status={row.status}
      onClick={onClick}
      aria-label={`${formatSpecType(row.specType)}, ${claimantDisplay}, ${row.status}`}
    >
      <style>{STYLES}</style>
      {isActiveTab && <span className="progress-row-accent-bar" />}
      <div className="progress-row-left">
        <span className="progress-row-spec-type">
          {formatSpecType(row.specType)}
        </span>
        <span
          className="progress-row-claimant"
          style={{
            color: claimantColor(row.claimantStatus),
            fontStyle: claimantItalic ? "italic" : "normal",
          }}
        >
          {claimantDisplay}
        </span>
      </div>
      <div className="progress-row-right">
        <ValidationGlyph
          summary={row.validation}
          warnings={row.validationWarnings}
        />
        {row.suggestionsOpen > 0 && (
          <span className="progress-row-suggestions">
            {row.suggestionsOpen}
          </span>
        )}
        <span className={`progress-row-status progress-row-status--${row.status}`}>
          {STATUS_LABEL[row.status]}
        </span>
      </div>
    </button>
  );
}

function ValidationGlyph({
  summary,
  warnings,
}: {
  summary: ValidationSummary;
  warnings: number;
}) {
  if (summary === "pass") {
    return (
      <Check
        size={11}
        strokeWidth={2}
        style={{ color: "var(--color-emerald)" }}
        aria-label="validation passing"
      />
    );
  }
  if (summary === "warn") {
    return (
      <span
        className="progress-row-warn"
        aria-label={`${warnings} validation warning${warnings === 1 ? "" : "s"}`}
      >
        <AlertCircle size={11} strokeWidth={2} />
        {warnings > 0 && <span>{warnings}</span>}
      </span>
    );
  }
  if (summary === "fail") {
    return (
      <AlertCircle
        size={11}
        strokeWidth={2}
        style={{ color: "var(--color-red)" }}
        aria-label="validation failing"
      />
    );
  }
  return (
    <Clock
      size={11}
      strokeWidth={2}
      style={{ color: "var(--color-text-tertiary)", opacity: 0.5 }}
      aria-label="validation pending"
    />
  );
}

const STYLES = `
  .progress-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    width: 100%;
    padding: 10px 0;
    background: transparent;
    border: none;
    cursor: pointer;
    font-family: var(--font-sans);
    text-align: left;
    position: relative;
    transition: background 120ms ease;
  }
  .progress-row:hover {
    background: var(--color-bg-card-hover, rgba(255, 255, 255, 0.02));
  }
  .progress-row:focus-visible {
    outline: 1px solid var(--color-accent);
    outline-offset: -1px;
  }
  .progress-row[data-active="true"] {
    padding-left: 8px;
  }
  .progress-row-accent-bar {
    position: absolute;
    left: -2px;
    top: 8px;
    bottom: 8px;
    width: 2px;
    background: var(--color-accent);
    border-radius: 1px;
  }
  .progress-row-left {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
    flex: 1;
  }
  .progress-row-spec-type {
    font-family: var(--font-mono);
    font-size: 11px;
    font-weight: 600;
    color: var(--color-text);
  }
  .progress-row-claimant {
    font-family: var(--font-sans);
    font-size: 11px;
    font-weight: 400;
    line-height: 1.6;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .progress-row-right {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-shrink: 0;
  }
  .progress-row-warn {
    display: inline-flex;
    align-items: center;
    gap: 2px;
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--color-amber);
  }
  .progress-row-suggestions {
    font-family: var(--font-mono);
    font-size: 9px;
    font-weight: 600;
    color: var(--color-red);
    background: rgba(239, 68, 100, 0.1);
    border-radius: 2px;
    padding: 1px 5px;
  }
  .progress-row-status {
    font-family: var(--font-mono);
    font-size: 9px;
    font-weight: 600;
    padding: 2px 7px;
    border-radius: 10px;
    line-height: 1.4;
    text-transform: lowercase;
  }
  .progress-row-status--drafting {
    background: var(--color-bg-card);
    border: 1px solid var(--color-border-strong, var(--color-text-tertiary));
    color: var(--color-text-secondary);
  }
  .progress-row-status--committed {
    background: var(--color-accent-glow);
    border: 1px solid rgba(0, 212, 170, 0.25);
    color: var(--color-accent);
  }
  .progress-row-status--ratified {
    background: rgba(68, 204, 119, 0.1);
    border: 1px solid rgba(68, 204, 119, 0.25);
    color: var(--color-emerald);
  }
  .progress-row-status--rejected {
    background: rgba(239, 68, 100, 0.1);
    border: 1px solid rgba(239, 68, 100, 0.25);
    color: var(--color-red);
  }
`;
