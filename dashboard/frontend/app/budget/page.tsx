"use client";

import { useState } from "react";
import { useQuery } from "urql";
import { ArrowDownRight } from "lucide-react";
import { CONTEXT_BUDGET_QUERY } from "@/lib/graphql/queries/budget";
import { useFeature } from "@/lib/hooks/use-feature-selector";
import { ProgressBar } from "@/components/shared/progress-bar";
import { CardSkeleton } from "@/components/shared/loading-skeleton";
import { formatTokens, formatPercent } from "@/lib/utils/format";

/* ── Types ─────────────────────────────────────────────────────── */

interface BudgetCut {
  file: string;
  originalTier: string;
  downgradedTo: string;
  tokensSaved: number;
  reason: string;
}

interface TaskBudget {
  taskId: string;
  title: string;
  stage: string;
  totalBudget: number;
  totalUsed: number;
  underBudget: boolean;
  allocated: {
    codeContext: {
      budget: number;
      used: number;
      filesFull: number | null;
      filesSkeleton: number | null;
      filesDropped: number | null;
    };
    taskContext: { budget: number; used: number };
    specContext: { budget: number; used: number };
    reserve: number;
  };
  cutsMade: BudgetCut[];
  cutsCount: number;
  tokensSaved: number;
}

/* ── Helpers ───────────────────────────────────────────────────── */

function utilizationColor(pct: number): string {
  if (pct >= 80) return "var(--color-amber)";
  if (pct >= 50) return "var(--color-emerald)";
  return "var(--color-text-secondary)";
}

function tierColor(tier: string): string {
  switch (tier) {
    case "full":
      return "var(--color-emerald)";
    case "skeleton":
    case "truncated":
      return "var(--color-amber)";
    case "dropped":
      return "var(--color-red)";
    default:
      return "var(--color-text-tertiary)";
  }
}

const stageStyle: Record<string, { color: string; bg: string }> = {
  developer: { color: "var(--color-blue)", bg: "rgba(75, 166, 238, 0.10)" },
  reviewer: { color: "var(--color-violet)", bg: "rgba(139, 92, 246, 0.10)" },
  architect: { color: "var(--color-cyan)", bg: "rgba(68, 221, 238, 0.10)" },
};

/* ── Left panel: Task list item ────────────────────────────────── */

function TaskListItem({
  task,
  selected,
  onSelect,
}: {
  task: TaskBudget;
  selected: boolean;
  onSelect: () => void;
}) {
  const utilization =
    task.totalBudget > 0 ? (task.totalUsed / task.totalBudget) * 100 : 0;
  const cc = task.allocated.codeContext;
  const tc = task.allocated.taskContext;
  const sc = task.allocated.specContext;
  const stage = stageStyle[task.stage] ?? stageStyle.developer;

  return (
    <button
      onClick={onSelect}
      className="flex w-full flex-col gap-2 border-l-2 px-4 py-3 text-left transition-colors hover:bg-bg-elevated/50"
      style={{
        borderLeftColor: selected ? "var(--color-accent)" : "transparent",
        backgroundColor: selected ? "rgba(0, 212, 170, 0.04)" : undefined,
      }}
    >
      {/* Top line: id, title, stage */}
      <div className="flex items-center gap-2">
        <span
          className="shrink-0 text-[11px] text-text-tertiary"
          style={{ fontFamily: "var(--font-mono)" }}
        >
          #{task.taskId}
        </span>
        <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-text">
          {task.title}
        </span>
        <span
          className="type-badge shrink-0 rounded-full px-2 py-0.5"
          style={{ color: stage.color, backgroundColor: stage.bg }}
        >
          {task.stage}
        </span>
      </div>

      {/* Bottom line: bar + utilization */}
      <div className="flex items-center gap-3">
        <div className="flex-1">
          <ProgressBar
            total={task.totalBudget}
            segments={[
              { value: cc.used, color: "var(--color-blue)", label: "Code" },
              { value: tc.used, color: "var(--color-violet)", label: "Task" },
              { value: sc.used, color: "var(--color-cyan)", label: "Spec" },
              {
                value: Math.max(0, task.totalBudget - task.totalUsed),
                color: "var(--color-text-tertiary)",
                label: "Reserve",
              },
            ]}
            height={4}
          />
        </div>
        <span
          className="shrink-0 text-[12px] font-semibold tabular-nums"
          style={{
            fontFamily: "var(--font-mono)",
            color: utilizationColor(utilization),
          }}
        >
          {formatPercent(utilization)}
        </span>
      </div>
    </button>
  );
}

/* ── Right panel: Detail view ──────────────────────────────────── */

function TaskDetail({ task }: { task: TaskBudget }) {
  const utilization =
    task.totalBudget > 0 ? (task.totalUsed / task.totalBudget) * 100 : 0;
  const cc = task.allocated.codeContext;
  const tc = task.allocated.taskContext;
  const sc = task.allocated.specContext;
  const stage = stageStyle[task.stage] ?? stageStyle.developer;

  const sortedCuts = [...task.cutsMade].sort(
    (a, b) => b.tokensSaved - a.tokensSaved
  );

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="border-b border-border/50 px-5 py-4">
        <div className="flex items-start justify-between">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span
                className="text-[11px] text-text-tertiary"
                style={{ fontFamily: "var(--font-mono)" }}
              >
                Task #{task.taskId}
              </span>
              <span
                className="type-badge rounded-full px-2 py-0.5"
                style={{ color: stage.color, backgroundColor: stage.bg }}
              >
                {task.stage}
              </span>
            </div>
            <h3 className="mt-1 text-[15px] font-semibold text-text">
              {task.title}
            </h3>
          </div>
          <div className="shrink-0 text-right">
            <span
              className="text-[22px] font-semibold tabular-nums"
              style={{
                fontFamily: "var(--font-mono)",
                color: utilizationColor(utilization),
              }}
            >
              {formatPercent(utilization)}
            </span>
            <div className="type-caption mt-0.5">utilization</div>
          </div>
        </div>
      </div>

      {/* Budget overview bar */}
      <div className="border-b border-border/50 px-5 py-4">
        <div className="mb-2 flex justify-between">
          <span className="type-kpi-label">Token allocation</span>
          <span
            className="text-[11px] tabular-nums text-text-tertiary"
            style={{ fontFamily: "var(--font-mono)" }}
          >
            {formatTokens(task.totalUsed)} / {formatTokens(task.totalBudget)}
          </span>
        </div>
        <ProgressBar
          total={task.totalBudget}
          segments={[
            { value: cc.used, color: "var(--color-blue)", label: "Code" },
            { value: tc.used, color: "var(--color-violet)", label: "Task" },
            { value: sc.used, color: "var(--color-cyan)", label: "Spec" },
            {
              value: Math.max(0, task.totalBudget - task.totalUsed),
              color: "var(--color-text-tertiary)",
              label: "Reserve",
            },
          ]}
          height={8}
        />

        {/* Allocation breakdown */}
        <div className="mt-3 grid grid-cols-4 gap-3">
          <AllocBlock
            label="Code context"
            used={cc.used}
            budget={cc.budget}
            color="var(--color-blue)"
          />
          <AllocBlock
            label="Task context"
            used={tc.used}
            budget={tc.budget}
            color="var(--color-violet)"
          />
          <AllocBlock
            label="Spec context"
            used={sc.used}
            budget={sc.budget}
            color="var(--color-cyan)"
          />
          <AllocBlock
            label="Reserve"
            used={0}
            budget={task.allocated.reserve}
            color="var(--color-text-tertiary)"
          />
        </div>
      </div>

      {/* File tiers */}
      {cc.filesFull != null && (
        <div className="border-b border-border/50 px-5 py-4">
          <div className="type-kpi-label mb-3">What the agent saw</div>
          <div className="flex gap-4">
            <TierCard
              label="Full"
              value={cc.filesFull}
              color="var(--color-emerald)"
              description="Complete file content"
            />
            <TierCard
              label="Skeleton"
              value={cc.filesSkeleton ?? 0}
              color="var(--color-amber)"
              description="Signatures only"
            />
            <TierCard
              label="Dropped"
              value={cc.filesDropped ?? 0}
              color="var(--color-red)"
              description="Not included"
            />
          </div>
        </div>
      )}

      {/* Cuts list */}
      {sortedCuts.length > 0 ? (
        <div className="min-h-0 flex-1 overflow-auto px-5 py-4">
          <div className="mb-3 flex items-baseline justify-between">
            <span className="type-kpi-label">
              Cuts made ({sortedCuts.length})
            </span>
            <span className="type-caption">
              {formatTokens(task.tokensSaved)} tokens saved
            </span>
          </div>

          {/* Column headers */}
          <div className="mb-1 flex items-center gap-3 px-2">
            <span className="type-table-header flex-1">File</span>
            <span className="type-table-header w-28 shrink-0 text-right">
              Tier change
            </span>
            <span className="type-table-header w-14 shrink-0 text-right">
              Saved
            </span>
          </div>

          <div className="space-y-0.5">
            {sortedCuts.map((cut, i) => (
              <div
                key={i}
                className="flex items-center gap-3 rounded px-2 py-1.5 transition-colors hover:bg-bg-card-hover/30"
              >
                <span
                  className="min-w-0 flex-1 truncate text-[12px] text-text-secondary"
                  style={{ fontFamily: "var(--font-mono)" }}
                >
                  {cut.file}
                </span>
                <span className="flex w-28 shrink-0 items-center justify-end gap-1 text-[11px]">
                  <span style={{ color: tierColor(cut.originalTier) }}>
                    {cut.originalTier}
                  </span>
                  <ArrowDownRight className="h-2.5 w-2.5 text-text-tertiary" />
                  <span style={{ color: tierColor(cut.downgradedTo) }}>
                    {cut.downgradedTo}
                  </span>
                </span>
                <span
                  className="w-14 shrink-0 text-right text-[11px] tabular-nums text-emerald"
                  style={{ fontFamily: "var(--font-mono)" }}
                >
                  −{formatTokens(cut.tokensSaved)}
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="flex flex-1 items-center justify-center px-5 py-8">
          <span className="type-caption">No cuts were needed for this task</span>
        </div>
      )}
    </div>
  );
}

/* ── Sub-components ────────────────────────────────────────────── */

function AllocBlock({
  label,
  used,
  budget,
  color,
}: {
  label: string;
  used: number;
  budget: number;
  color: string;
}) {
  return (
    <div>
      <div className="flex items-center gap-1.5">
        <div
          className="h-2 w-2 rounded-full"
          style={{ backgroundColor: color }}
        />
        <span className="type-caption">{label}</span>
      </div>
      <div className="mt-1 pl-3.5">
        <span
          className="text-[13px] font-medium tabular-nums"
          style={{ fontFamily: "var(--font-mono)", color }}
        >
          {formatTokens(used)}
        </span>
        <span className="type-caption ml-1">/ {formatTokens(budget)}</span>
      </div>
    </div>
  );
}

function TierCard({
  label,
  value,
  color,
  description,
}: {
  label: string;
  value: number;
  color: string;
  description: string;
}) {
  return (
    <div className="flex-1 rounded-lg bg-bg/60 px-3 py-2.5">
      <div
        className="text-[18px] font-semibold tabular-nums"
        style={{ fontFamily: "var(--font-mono)", color }}
      >
        {value}
      </div>
      <div className="mt-0.5 text-[12px] font-medium text-text">{label}</div>
      <div className="type-caption mt-0.5">{description}</div>
    </div>
  );
}

function Stat({
  label,
  value,
  color,
}: {
  label: string;
  value: number | string;
  color?: string;
}) {
  return (
    <div className="flex items-baseline gap-2">
      <span
        className="text-[18px] font-semibold tabular-nums"
        style={{
          fontFamily: "var(--font-mono)",
          color: color ?? "var(--color-text)",
        }}
      >
        {value}
      </span>
      <span className="type-kpi-label">{label}</span>
    </div>
  );
}

/* ── Page ──────────────────────────────────────────────────────── */

export default function BudgetPage() {
  const { selectedFeature } = useFeature();
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [{ data, fetching, error }] = useQuery({
    query: CONTEXT_BUDGET_QUERY,
    variables: { feature: selectedFeature },
  });

  if (fetching) {
    return (
      <div className="grid gap-4 md:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <CardSkeleton key={i} />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="surface p-4 text-red">Error: {error.message}</div>
    );
  }

  const budget = data?.contextBudget;
  if (!budget || budget.tasks.length === 0) {
    return (
      <div className="text-text-secondary">
        No budget data found. Budget files are generated during{" "}
        <code className="rounded bg-bg-card px-1.5 py-0.5 text-accent">
          speed run
        </code>
        .
      </div>
    );
  }

  const s = budget.summary;
  const tasks: TaskBudget[] = budget.tasks;
  const activeTask =
    tasks.find((t) => t.taskId === selectedTaskId) ?? tasks[0];

  return (
    <div className="flex h-full flex-col gap-4">
      {/* Summary bar */}
      <div className="surface flex items-center gap-8 px-5 py-3">
        <Stat label="Tasks" value={s.taskCount} />
        <Stat label="Budget" value={formatTokens(s.totalBudget)} />
        <Stat
          label="Used"
          value={formatTokens(s.totalUsed)}
          color="var(--color-accent)"
        />
        <Stat
          label="Utilization"
          value={formatPercent(s.utilizationPct)}
          color={utilizationColor(s.utilizationPct)}
        />

        <div className="ml-auto flex items-center gap-4">
          <span className="type-caption">
            {s.underBudgetCount} under · {s.overBudgetCount} over
          </span>
          <div className="w-48">
            <ProgressBar
              total={s.totalBudget}
              segments={[
                {
                  value: s.totalUsed,
                  color: "var(--color-accent)",
                  label: "Used",
                },
                {
                  value: Math.max(0, s.totalBudget - s.totalUsed),
                  color: "var(--color-text-tertiary)",
                  label: "Remaining",
                },
              ]}
              height={4}
            />
          </div>
        </div>
      </div>

      {/* Split panel */}
      <div className="flex min-h-0 flex-1 gap-4" style={{ minHeight: 500 }}>
        {/* Left: task list */}
        <div className="surface flex w-80 shrink-0 flex-col overflow-hidden">
          <div className="border-b border-border/50 px-4 py-2">
            <span className="type-table-header">Tasks</span>
          </div>
          <div className="flex-1 overflow-auto">
            {tasks.map((task) => (
              <TaskListItem
                key={task.taskId}
                task={task}
                selected={activeTask.taskId === task.taskId}
                onSelect={() => setSelectedTaskId(task.taskId)}
              />
            ))}
          </div>
        </div>

        {/* Right: detail */}
        <div className="surface min-w-0 flex-1 overflow-hidden">
          <TaskDetail task={activeTask} />
        </div>
      </div>
    </div>
  );
}
