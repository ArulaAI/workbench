"use client";

import React from "react";

interface RunHeaderProps {
  relativeTime: string;
  onBackToLatest: () => void;
}

export function RunHeader({ relativeTime, onBackToLatest }: RunHeaderProps) {
  return (
    <>
      <style>{`
        @keyframes rh-enter {
          from { opacity: 0; max-height: 0; }
          to   { opacity: 1; max-height: 40px; }
        }
        .rh-container {
          display: flex;
          align-items: center;
          justify-content: space-between;
          background: var(--color-bg);
          border-bottom: 1px solid var(--color-border);
          padding: 6px 12px;
          overflow: hidden;
          animation: rh-enter 150ms ease forwards;
        }
        @media (prefers-reduced-motion: reduce) {
          .rh-container {
            animation: none;
          }
        }
        .rh-label {
          font-family: var(--font-mono);
          font-size: 10px;
          font-weight: 400;
          color: var(--color-text-tertiary);
        }
        .rh-link {
          font-family: var(--font-mono);
          font-size: 10px;
          font-weight: 500;
          color: var(--color-accent);
          background: none;
          border: none;
          cursor: pointer;
          padding: 0;
          line-height: inherit;
        }
        .rh-link:hover {
          text-decoration: underline;
        }
      `}</style>
      <div className="rh-container" role="status" aria-live="polite">
        <span className="rh-label">Viewing audit from {relativeTime}</span>
        <button className="rh-link" onClick={onBackToLatest}>
          ← Latest
        </button>
      </div>
    </>
  );
}

export default RunHeader;
