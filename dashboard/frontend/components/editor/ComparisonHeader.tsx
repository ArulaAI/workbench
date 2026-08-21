"use client";

import React from "react";

interface ComparisonHeaderProps {
  olderTime: string;
  newerTime: string;
  olderCount: number;
  newerCount: number;
}

export function ComparisonHeader({
  olderTime,
  newerTime,
  olderCount,
  newerCount,
}: ComparisonHeaderProps) {
  const delta = newerCount - olderCount;

  let deltaStr: string;
  if (delta === 0) {
    deltaStr = "(0)";
  } else if (delta > 0) {
    deltaStr = `(+${delta})`;
  } else {
    // U+2212 MINUS SIGN, matching spec: (−3)
    deltaStr = `(\u2212${Math.abs(delta)})`;
  }

  let deltaColor: string;
  if (newerCount < olderCount) {
    deltaColor = "var(--color-emerald)";
  } else if (newerCount > olderCount) {
    deltaColor = "var(--color-red)";
  } else {
    deltaColor = "var(--color-text-tertiary)";
  }

  const srText = `Comparing audit from ${olderTime} with ${newerTime}. ${olderCount} issues to ${newerCount} issues.`;

  return (
    <>
      <style>{`
        @keyframes ch-enter {
          from { opacity: 0; max-height: 0; }
          to   { opacity: 1; max-height: 40px; }
        }
        .ch-container {
          background: var(--color-bg);
          padding: 10px 12px;
          overflow: hidden;
          animation: ch-enter 150ms ease forwards;
        }
        @media (prefers-reduced-motion: reduce) {
          .ch-container {
            animation: none;
          }
        }
        .ch-sr-only {
          position: absolute;
          width: 1px;
          height: 1px;
          padding: 0;
          margin: -1px;
          overflow: hidden;
          clip: rect(0, 0, 0, 0);
          white-space: nowrap;
          border-width: 0;
        }
        .ch-row {
          font-family: var(--font-mono);
          font-size: 11px;
          font-weight: 500;
          line-height: 1.5;
        }
        .ch-row-timestamps {
          color: var(--color-text);
        }
        .ch-row-counts {
          color: var(--color-text-secondary);
        }
      `}</style>
      <div className="ch-container" role="status" aria-live="polite">
        <span className="ch-sr-only">{srText}</span>
        <div aria-hidden="true">
          <div className="ch-row ch-row-timestamps">
            Comparing: {olderTime} → {newerTime}
          </div>
          <div className="ch-row ch-row-counts">
            {olderCount} issues → {newerCount} issues{" "}
            <span style={{ color: deltaColor }}>{deltaStr}</span>
          </div>
        </div>
      </div>
    </>
  );
}

export default ComparisonHeader;
