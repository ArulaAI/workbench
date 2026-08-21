"use client";

import type { ReactNode } from "react";

interface EditorialGridProps {
  definePanel: ReactNode;
  judgePanel: ReactNode;
  executePanel: ReactNode;
  learnPanel: ReactNode;
}

export function EditorialGrid({
  definePanel,
  judgePanel,
  executePanel,
  learnPanel,
}: EditorialGridProps) {
  return (
    <div
      style={{
        flex: 1,
        overflow: "hidden",
        display: "grid",
        gridTemplateColumns: "260px 1fr 320px",
        gridTemplateRows: "3fr 1fr",
        gap: 1,
        background: "var(--color-border)",
      }}
    >
      <div
        data-testid="editorial-grid-define"
        style={{
          gridColumn: "1",
          gridRow: "1 / 3",
          background: "var(--color-bg-elevated)",
          overflowY: "auto",
          padding: "20px 24px",
        }}
      >
        {definePanel}
      </div>
      <div
        data-testid="editorial-grid-judge"
        style={{
          gridColumn: "2",
          gridRow: "1",
          background: "var(--color-bg)",
          overflowY: "auto",
          padding: "20px 24px",
        }}
      >
        {judgePanel}
      </div>
      <div
        data-testid="editorial-grid-execute"
        style={{
          gridColumn: "2",
          gridRow: "2",
          background: "var(--color-bg)",
          overflowY: "auto",
          padding: "20px 24px",
        }}
      >
        {executePanel}
      </div>
      <div
        data-testid="editorial-grid-learn"
        style={{
          gridColumn: "3",
          gridRow: "1 / 3",
          background: "var(--color-bg-elevated)",
          overflowY: "auto",
          padding: "20px 24px",
        }}
      >
        {learnPanel}
      </div>
    </div>
  );
}
