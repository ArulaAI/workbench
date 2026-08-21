"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { ProgressRow, type ProgressRowData } from "./ProgressRow";
import { ProgressSummary } from "./ProgressSummary";

/**
 * ProgressOverview — top-of-context-panel section showing per-spec progress.
 *
 * Single 5-column layout regardless of roster size. Rows are composed by
 * the parent (CeremonyLayout) from ceremonyClaims + drafts + suggestions;
 * this component just renders them.
 *
 * Default open state is computed from `rows.length > 3` per the design
 * spec, overridable via `defaultOpen` for testing.
 */

export type { ProgressRowData } from "./ProgressRow";

interface ProgressOverviewProps {
  rows: ProgressRowData[];
  activeSpecType: string;
  onRowClick: (specType: string) => void;
  defaultOpen?: boolean;
}

export function ProgressOverview({
  rows,
  activeSpecType,
  onRowClick,
  defaultOpen,
}: ProgressOverviewProps) {
  const initialOpen = defaultOpen ?? rows.length > 3;
  const [open, setOpen] = useState(initialOpen);

  if (rows.length === 0) {
    return (
      <div className="progress-overview progress-overview--empty">
        <style>{STYLES}</style>
        <div className="progress-overview-header">
          <span className="progress-overview-title">Progress</span>
        </div>
        <div className="progress-overview-empty-text">
          No specs drafted yet · claim a tab to begin
        </div>
      </div>
    );
  }

  const committedCount = rows.filter(
    (r) => r.status === "committed" || r.status === "ratified"
  ).length;
  const ratifiedCount = rows.filter((r) => r.status === "ratified").length;

  return (
    <section
      className="progress-overview"
      aria-label="Ceremony progress"
    >
      <style>{STYLES}</style>
      <button
        className="progress-overview-header"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        {open ? (
          <ChevronDown size={11} strokeWidth={2} />
        ) : (
          <ChevronRight size={11} strokeWidth={2} />
        )}
        <span className="progress-overview-title">Progress</span>
        <span className="progress-overview-count">{rows.length}</span>
      </button>
      {open && (
        <>
          <div className="progress-overview-rows">
            {rows.map((row) => (
              <ProgressRow
                key={row.specType}
                row={row}
                isActiveTab={row.specType === activeSpecType}
                onClick={() => onRowClick(row.specType)}
              />
            ))}
          </div>
          <ProgressSummary
            totalDrafted={rows.length}
            totalCommitted={committedCount}
            totalRatified={ratifiedCount}
          />
        </>
      )}
    </section>
  );
}

const STYLES = `
  .progress-overview {
    padding: 16px 0 0 0;
    border-bottom: 1px solid var(--color-border-light, rgba(255, 255, 255, 0.04));
    margin-bottom: 12px;
  }
  .progress-overview-header {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    padding: 0 0 8px 0;
    background: none;
    border: none;
    cursor: pointer;
    color: var(--color-text-tertiary);
    font-family: var(--font-mono);
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    transition: color 150ms ease;
  }
  .progress-overview-header:hover {
    color: var(--color-text-secondary);
  }
  .progress-overview-header:focus-visible {
    outline: 1px solid var(--color-accent);
    outline-offset: 2px;
    border-radius: 2px;
  }
  .progress-overview-title {
    flex: 1;
    text-align: left;
  }
  .progress-overview-count {
    font-family: var(--font-mono);
    font-size: 9px;
    color: var(--color-text-tertiary);
  }
  .progress-overview-rows {
    display: flex;
    flex-direction: column;
  }
  .progress-overview-empty-text {
    padding: 8px 0 16px 0;
    font-family: var(--font-sans);
    font-size: 11px;
    font-style: italic;
    color: var(--color-text-tertiary);
  }
`;
