"use client";

import { coverageColor } from "@/lib/utils/colors";
import { ProgressBar } from "@/components/shared/progress-bar";

interface Built {
  coveragePct: number | null;
  criteriaPassed: number | null;
  criteriaTotal: number | null;
  guardianVerdict: string | null;
  taskProgress: number | null;
  tasksDone: number | null;
  tasksTotal: number | null;
  blockedCount: number;
  completedAt: string | null;
}

interface BuiltCellProps {
  state: "complete" | "executing" | "writing" | "unplanned";
  built: Built;
}

export function BuiltCell({ state, built }: BuiltCellProps) {
  const cellStyle = {
    background: "var(--color-bg)",
    padding: "16px 20px",
    minHeight: 60,
  };

  if (state === "complete") {
    return (
      <div style={cellStyle}>
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 24,
            fontWeight: 600,
            color: built.coveragePct != null ? coverageColor(built.coveragePct) : "var(--color-text-tertiary)",
            lineHeight: 1.1,
          }}
        >
          {built.coveragePct != null ? `${built.coveragePct}%` : "\u2014"}
        </div>
        {built.criteriaTotal != null && built.criteriaTotal > 0 && (
          <div
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 13,
              fontWeight: 500,
              color: "var(--color-text-secondary)",
              marginTop: 4,
            }}
          >
            {built.criteriaPassed ?? 0}/{built.criteriaTotal}
          </div>
        )}
        {built.guardianVerdict && (
          <div
            style={{
              fontFamily: "var(--font-sans)",
              fontSize: 12,
              fontWeight: 400,
              color: "var(--color-text-secondary)",
              marginTop: 4,
            }}
          >
            {built.guardianVerdict}
          </div>
        )}
        {built.completedAt && (
          <div
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              fontWeight: 400,
              color: "var(--color-text-tertiary)",
              marginTop: 4,
            }}
          >
            {built.completedAt}
          </div>
        )}
      </div>
    );
  }

  if (state === "executing") {
    const total = built.tasksTotal ?? 0;
    const done = built.tasksDone ?? 0;
    const inProgress = Math.max(0, total - done - built.blockedCount);
    const segments = [
      {
        value: done,
        color: "var(--color-emerald)",
        label: "Done",
      },
      {
        value: built.blockedCount,
        color: "var(--color-red)",
        label: "Blocked",
      },
      {
        value: inProgress,
        color: "var(--color-text-tertiary)",
        label: "In progress",
      },
    ];
    return (
      <div style={cellStyle}>
        <ProgressBar segments={segments} total={total} height={6} />
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 12,
            fontWeight: 400,
            color: "var(--color-text-secondary)",
            marginTop: 8,
          }}
        >
          {done}/{total} tasks
        </div>
        {built.blockedCount > 0 && (
          <div
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 12,
              fontWeight: 400,
              color: "var(--color-red)",
              marginTop: 2,
            }}
          >
            {built.blockedCount} blocked
          </div>
        )}
      </div>
    );
  }

  // writing or unplanned — compact single-line cell (S4)
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
        {state === "writing" ? "Specs in progress" : "\u2014"}
      </span>
    </div>
  );
}
