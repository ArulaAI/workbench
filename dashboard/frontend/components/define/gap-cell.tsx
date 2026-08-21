"use client";

import { RefMarker } from "@/components/define/ref-marker";

interface GapEscalation {
  description: string;
  linkedWarningId: string | null;
}

interface Gap {
  escalationCount: number;
  escalations: GapEscalation[];
  unverifiableCount: number;
  reworkCount: number;
}

interface GapCellProps {
  state: "complete" | "executing" | "writing" | "unplanned";
  gap: Gap;
}

export function GapCell({ state, gap }: GapCellProps) {
  const cellStyle = {
    background: "var(--color-bg)",
    padding: "16px 20px",
    minHeight: 60,
  };

  // writing or unplanned — compact single-line cell (S4)
  if (state === "writing" || state === "unplanned") {
    return (
      <div style={{ background: "var(--color-bg)", padding: "10px 20px" }}>
        <span
          style={{
            fontFamily: "var(--font-sans)",
            fontSize: 11,
            fontWeight: 400,
            fontStyle: "italic",
            color: "var(--color-text-tertiary)",
          }}
        >
          {state === "writing" ? "\u2014" : "\u2014"}
        </span>
      </div>
    );
  }

  // complete or executing
  let refIndex = 0;
  const hasContent =
    gap.escalationCount > 0 ||
    gap.unverifiableCount > 0 ||
    gap.reworkCount > 0;

  if (!hasContent) {
    return <div style={cellStyle} />;
  }

  return (
    <div style={cellStyle}>
      {gap.escalationCount > 0 && (
        <div style={{ marginBottom: gap.unverifiableCount > 0 || gap.reworkCount > 0 ? 8 : 0 }}>
          <div
            style={{
              fontFamily: "var(--font-sans)",
              fontSize: 12,
              fontWeight: 500,
              color: "var(--color-text-secondary)",
              marginBottom: 4,
            }}
          >
            {gap.escalationCount} escalation{gap.escalationCount !== 1 ? "s" : ""}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {gap.escalations.map((esc, i) => {
              const markerNum = esc.linkedWarningId !== null ? ++refIndex : null;
              return (
                <div
                  key={i}
                  style={{ display: "flex", alignItems: "flex-start", gap: 4 }}
                >
                  <div
                    style={{
                      fontFamily: "var(--font-sans)",
                      fontSize: 12,
                      fontWeight: 400,
                      color: "var(--color-text-secondary)",
                      lineHeight: 1.4,
                      display: "-webkit-box",
                      WebkitLineClamp: 2,
                      WebkitBoxOrient: "vertical",
                      overflow: "hidden",
                      flex: 1,
                    }}
                  >
                    {esc.description}
                  </div>
                  {markerNum !== null && (
                    <RefMarker number={markerNum} description={esc.description} />
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {gap.unverifiableCount > 0 && (
        <div
          style={{
            fontFamily: "var(--font-sans)",
            fontSize: 12,
            fontWeight: 400,
            color: "var(--color-text-secondary)",
            marginBottom: gap.reworkCount > 0 ? 4 : 0,
          }}
        >
          {gap.unverifiableCount} unverifiable
        </div>
      )}

      {gap.reworkCount > 0 && (
        <div
          style={{
            fontFamily: "var(--font-sans)",
            fontSize: 12,
            fontWeight: 400,
            color: "var(--color-text-secondary)",
          }}
        >
          {gap.reworkCount} rework
        </div>
      )}
    </div>
  );
}
