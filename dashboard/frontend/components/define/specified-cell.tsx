import { StateBadge } from "./state-badge";
import { SpecPill } from "./spec-pill";
import type { BadgeState } from "./state-badge";
import type { PillState } from "./spec-pill";

interface SpecInfo {
  exists: boolean;
  path: string | null;
  auditStatus: string;
  warningCount: number;
  warnings: string[];
}

interface Specified {
  productSpec: SpecInfo;
  technicalSpec: SpecInfo;
  designSpec: SpecInfo;
  openQuestions: number;
  sizingEstimate: number | null;
}

interface SpecifiedCellProps {
  name: string;
  state: BadgeState;
  specified: Specified;
}

function truncateName(name: string, maxLen = 32): string {
  return name.length > maxLen ? name.slice(0, maxLen) + "\u2026" : name;
}

function derivePillState(spec: SpecInfo): PillState {
  if (!spec.exists) return "missing";
  if (spec.auditStatus === "warning" || spec.auditStatus === "error") return "warning";
  return "present";
}

export function SpecifiedCell({ name, state, specified }: SpecifiedCellProps) {
  if (state === "unplanned" || state === "writing") {
    return (
      <div
        style={{
          background: "var(--color-bg)",
          padding: "10px 20px",
          display: "flex",
          alignItems: "center",
          gap: 8,
          minWidth: 0,
        }}
      >
        <span
          style={{
            fontFamily: "var(--font-sans)",
            fontSize: 13,
            fontWeight: 500,
            color: "var(--color-text)",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            minWidth: 0,
          }}
        >
          {truncateName(name)}
        </span>
        <StateBadge state={state} />
      </div>
    );
  }

  const allWarnings = [
    ...specified.productSpec.warnings,
    ...specified.technicalSpec.warnings,
    ...specified.designSpec.warnings,
  ];
  const totalWarnings = allWarnings.length;

  return (
    <div
      style={{
        background: "var(--color-bg)",
        padding: "16px 20px",
        display: "flex",
        flexDirection: "column",
        gap: 8,
        minWidth: 0,
      }}
    >
      {/* Name + state badge */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          minWidth: 0,
        }}
      >
        <span
          style={{
            fontFamily: "var(--font-sans)",
            fontSize: 13,
            fontWeight: 500,
            color: "var(--color-text)",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            minWidth: 0,
          }}
        >
          {truncateName(name)}
        </span>
        <StateBadge state={state} />
      </div>

      {/* Spec pills */}
      <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
        <SpecPill label="Product" state={derivePillState(specified.productSpec)} />
        <SpecPill label="Technical" state={derivePillState(specified.technicalSpec)} />
        <SpecPill label="Design" state={derivePillState(specified.designSpec)} />
      </div>

      {/* Audit warnings */}
      {totalWarnings > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <span
            style={{
              fontFamily: "var(--font-sans)",
              fontSize: 11,
              fontWeight: 500,
              color: "var(--color-amber)",
              lineHeight: 1.4,
            }}
          >
            {totalWarnings} warning{totalWarnings !== 1 ? "s" : ""}
          </span>
          {allWarnings.map((warning, i) => (
            <span
              key={i}
              style={{
                fontFamily: "var(--font-sans)",
                fontSize: 11,
                fontWeight: 400,
                color: "var(--color-amber)",
                lineHeight: 1.4,
              }}
            >
              {warning}
            </span>
          ))}
        </div>
      )}

      {/* Open questions */}
      {specified.openQuestions > 0 && (
        <span
          style={{
            fontFamily: "var(--font-sans)",
            fontSize: 11,
            fontWeight: 400,
            color: "var(--color-text-tertiary)",
            lineHeight: 1.4,
          }}
        >
          {specified.openQuestions} open question
          {specified.openQuestions !== 1 ? "s" : ""}
        </span>
      )}

      {/* Sizing estimate */}
      {specified.sizingEstimate && (
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            fontWeight: 400,
            color: "var(--color-text-secondary)",
            lineHeight: 1.4,
          }}
        >
          {specified.sizingEstimate}
        </span>
      )}
    </div>
  );
}
