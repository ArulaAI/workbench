"use client";

interface ProgressSummaryProps {
  totalDrafted: number;
  totalCommitted: number;
  totalRatified: number;
}

/**
 * ProgressSummary — single-line footer under the ProgressOverview rows.
 *
 * Same format for every ceremony regardless of roster size:
 * "N of M committed · K of M ratified". Sole-actor ceremonies show the
 * committed and ratified counts converging on the same number because
 * `commitSpec` writes the ratification inline when no eligible ratifier
 * exists.
 */

export function ProgressSummary({
  totalDrafted,
  totalCommitted,
  totalRatified,
}: ProgressSummaryProps) {
  return (
    <div className="progress-summary">
      <style>{`
        .progress-summary {
          padding: 12px 0 16px 0;
          border-top: 1px solid var(--color-border-light, rgba(255, 255, 255, 0.04));
          font-family: var(--font-mono);
          font-size: 11px;
          color: var(--color-text-secondary);
          line-height: 1.4;
        }
        .progress-summary strong {
          color: var(--color-text);
          font-weight: 600;
        }
      `}</style>
      <strong>{totalCommitted}</strong> of <strong>{totalDrafted}</strong> committed
      {" · "}
      <strong>{totalRatified}</strong> of <strong>{totalDrafted}</strong> ratified
    </div>
  );
}
