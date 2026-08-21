"use client";

import type { CSSProperties, MouseEvent } from "react";

export interface VerdictDotProps {
  status: "pass" | "warn" | "fail";
  selected: boolean;
  compareSelected: boolean;
  isLatest: boolean;
  onClick: () => void;
  onShiftClick: () => void;
  tooltip: string;
  tabIndex: number;
}

function statusColor(status: VerdictDotProps["status"]): string {
  if (status === "pass") return "var(--color-emerald)";
  if (status === "fail") return "var(--color-red)";
  return "var(--color-amber)";
}

export function VerdictDot({
  status,
  selected,
  compareSelected,
  isLatest,
  onClick,
  onShiftClick,
  tooltip,
  tabIndex,
}: VerdictDotProps) {
  const prominent = selected || compareSelected || isLatest;
  const dotSize = prominent ? 8 : 6;
  const baseOpacity = prominent ? 1.0 : 0.5;

  const ariaLabel =
    `Audit run from ${tooltip}, verdict: ${status}` +
    (selected || compareSelected ? ", selected" : "");

  function handleClick(e: MouseEvent<HTMLButtonElement>) {
    if (e.shiftKey) {
      onShiftClick();
    } else {
      onClick();
    }
  }

  return (
    <button
      className="fv-verdict-dot vd-btn"
      onClick={handleClick}
      title={tooltip}
      aria-label={ariaLabel}
      aria-pressed={selected || compareSelected}
      tabIndex={tabIndex}
    >
      <span
        className="vd-dot-inner"
        data-selected={selected || undefined}
        data-compare={compareSelected || undefined}
        style={{
          "--vd-base-opacity": baseOpacity,
          width: dotSize,
          height: dotSize,
          background: statusColor(status),
        } as CSSProperties}
      />
    </button>
  );
}

export default VerdictDot;
