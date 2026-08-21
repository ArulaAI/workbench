"use client";

import { useEffect } from "react";
import { useQuery, useSubscription } from "urql";
import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import {
  TOKEN_BURN_AGGREGATE_QUERY,
  TOKEN_BURN_TIME_SERIES_QUERY,
  TOKEN_BURN_QUERY,
  AGENT_RUN_SUBSCRIPTION,
} from "@/lib/graphql/queries/analytics";
import { useFeature } from "@/lib/hooks/use-feature-selector";
import { ProgressBar } from "@/components/shared/progress-bar";
import { CardSkeleton } from "@/components/shared/loading-skeleton";
import { formatCost, formatTokens, formatDuration } from "@/lib/utils/format";
import { getModelColor, shortModel } from "@/lib/utils/model";

/* ── Constants ─────────────────────────────────────────────────── */

const AGENT_COLORS = [
  "#00d4aa", "#8b5cf6", "#4ba6ee", "#f0b232", "#44cc77",
  "#ef4464", "#ff6699", "#44ddee", "#e4e4e9",
];

const tooltipStyle = {
  contentStyle: {
    backgroundColor: "#1c1c27",
    border: "1px solid rgba(255,255,255,0.06)",
    borderRadius: 8,
    boxShadow: "0 4px 12px rgba(0,0,0,0.4)",
    color: "#e4e4e9",
    fontSize: 12,
    fontFamily: "var(--font-mono)",
  },
  cursor: { stroke: "rgba(0, 212, 170, 0.3)" },
};

/* ── Types ─────────────────────────────────────────────────────── */

interface AggRow {
  groupKey: string;
  runCount: number;
  totalCostUsd: number;
  totalInputTokens: number;
  totalOutputTokens: number;
  totalCacheReadTokens: number;
  totalCacheCreationTokens: number;
}

interface TsRow {
  bucket: string;
  costUsd: number;
  cumulativeCostUsd: number;
  runCount: number;
  totalTokens: number;
}

interface RunRow {
  id: string;
  feature: string;
  agentType: string;
  models: string;
  totalCostUsd: number;
  numTurns: number;
  durationMs: number;
  inputTokens: number;
  outputTokens: number;
  cacheReadTokens: number;
}

/* ── Page ──────────────────────────────────────────────────────── */

export default function AnalyticsPage() {
  const { selectedFeature } = useFeature();

  const [{ data: byFeature, fetching: f1 }, reexecFeature] = useQuery({
    query: TOKEN_BURN_AGGREGATE_QUERY,
    variables: { groupBy: "FEATURE", feature: selectedFeature },
  });
  const [{ data: byAgent, fetching: f2 }, reexecAgent] = useQuery({
    query: TOKEN_BURN_AGGREGATE_QUERY,
    variables: { groupBy: "AGENT_TYPE", feature: selectedFeature },
  });
  const [{ data: byModel, fetching: f3 }, reexecModel] = useQuery({
    query: TOKEN_BURN_AGGREGATE_QUERY,
    variables: { groupBy: "MODEL", feature: selectedFeature },
  });
  const [{ data: timeSeries, fetching: f4 }, reexecTs] = useQuery({
    query: TOKEN_BURN_TIME_SERIES_QUERY,
    variables: { feature: selectedFeature, bucketMinutes: 60 },
  });
  const [{ data: runs, fetching: f5 }, reexecRuns] = useQuery({
    query: TOKEN_BURN_QUERY,
    variables: { feature: selectedFeature, limit: 20 },
  });

  // Live refresh when new agent runs complete
  const [{ data: subData }] = useSubscription({
    query: AGENT_RUN_SUBSCRIPTION,
    variables: { feature: selectedFeature },
  });

  useEffect(() => {
    if (!subData?.agentRunCompleted) return;
    const opts = { requestPolicy: "network-only" as const };
    reexecFeature(opts);
    reexecAgent(opts);
    reexecModel(opts);
    reexecTs(opts);
    reexecRuns(opts);
  }, [subData, reexecFeature, reexecAgent, reexecModel, reexecTs, reexecRuns]);

  if (f1 || f2 || f3 || f4 || f5) {
    return (
      <div className="grid gap-4 md:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <CardSkeleton key={i} />
        ))}
      </div>
    );
  }

  const featureData: AggRow[] = byFeature?.tokenBurnAggregate ?? [];
  const agentData: AggRow[] = byAgent?.tokenBurnAggregate ?? [];
  const modelData: AggRow[] = byModel?.tokenBurnAggregate ?? [];
  const tsData: TsRow[] = timeSeries?.tokenBurnTimeSeries ?? [];
  const runData: RunRow[] = runs?.tokenBurn ?? [];

  const totalCost = featureData.reduce((s, r) => s + r.totalCostUsd, 0);
  const totalRuns = featureData.reduce((s, r) => s + r.runCount, 0);
  const totalCacheRead = featureData.reduce((s, r) => s + r.totalCacheReadTokens, 0);
  const totalInput = featureData.reduce((s, r) => s + r.totalInputTokens, 0);
  const cacheEfficiency =
    totalInput + totalCacheRead > 0
      ? (totalCacheRead / (totalInput + totalCacheRead)) * 100
      : 0;
  const avgCost = totalRuns > 0 ? totalCost / totalRuns : 0;

  return (
    <div className="space-y-4">
      {/* ── Summary bar ──────────────────────────────────── */}
      <div className="surface flex items-center gap-8 px-5 py-3">
        <Stat label="Total Cost" value={formatCost(totalCost)} color="var(--color-accent)" />
        <Stat label="Runs" value={totalRuns} />
        <Stat label="Avg / Run" value={formatCost(avgCost)} />
        <Stat
          label="Cache Efficiency"
          value={`${cacheEfficiency.toFixed(1)}%`}
          color="var(--color-emerald)"
        />
        <div className="ml-auto flex items-center gap-4">
          <span className="type-caption">
            {featureData.length} features · {modelData.length} models
          </span>
          <div className="w-48">
            <ProgressBar
              total={totalCost}
              segments={featureData.map((f, i) => ({
                value: f.totalCostUsd,
                color: AGENT_COLORS[i % AGENT_COLORS.length],
                label: f.groupKey,
              }))}
              height={4}
            />
          </div>
        </div>
      </div>

      {/* ── Hero: cumulative cost area chart ─────────────── */}
      <div className="surface overflow-hidden p-5">
        <div className="mb-4 flex items-baseline justify-between">
          <span className="type-section-header">Cumulative Cost</span>
          <span
            className="text-[11px] tabular-nums text-text-tertiary"
            style={{ fontFamily: "var(--font-mono)" }}
          >
            {tsData.length} time buckets
          </span>
        </div>
        <ResponsiveContainer width="100%" height={300}>
          <AreaChart data={tsData} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id="costGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#00d4aa" stopOpacity={0.25} />
                <stop offset="100%" stopColor="#00d4aa" stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <XAxis
              dataKey="bucket"
              tick={{ fill: "#55556a", fontSize: 10 }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(v: string) => {
                const d = new Date(v);
                return `${d.getHours()}:${d.getMinutes().toString().padStart(2, "0")}`;
              }}
            />
            <YAxis
              tick={{ fill: "#55556a", fontSize: 10 }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(v: number) => `$${v.toFixed(0)}`}
              width={40}
            />
            <Tooltip
              {...tooltipStyle}
              formatter={(v: number) => [formatCost(v), "Total"]}
              labelFormatter={(v: string) => {
                const d = new Date(v);
                return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
              }}
            />
            <Area
              type="monotone"
              dataKey="cumulativeCostUsd"
              stroke="#00d4aa"
              strokeWidth={2}
              fill="url(#costGradient)"
              dot={false}
              activeDot={{
                r: 4,
                fill: "#00d4aa",
                stroke: "#0c0c10",
                strokeWidth: 2,
              }}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* ── Breakdown row: Feature / Agent / Model ───────── */}
      <div className="grid gap-4 md:grid-cols-3">
        <BreakdownPanel
          title="By Feature"
          data={featureData}
          maxCost={Math.max(...featureData.map((d) => d.totalCostUsd), 1)}
          colorFn={(_, i) => AGENT_COLORS[i % AGENT_COLORS.length]}
        />
        <BreakdownPanel
          title="By Agent Type"
          data={agentData}
          maxCost={Math.max(...agentData.map((d) => d.totalCostUsd), 1)}
          colorFn={(_, i) => AGENT_COLORS[i % AGENT_COLORS.length]}
        />
        <BreakdownPanel
          title="By Model"
          data={modelData}
          maxCost={Math.max(...modelData.map((d) => d.totalCostUsd), 1)}
          colorFn={(row) => getModelColor(row.groupKey)}
        />
      </div>

      {/* ── Runs table ───────────────────────────────────── */}
      <div className="surface overflow-hidden">
        <div className="border-b border-border/50 px-5 py-3">
          <span className="type-section-header">Most Expensive Runs</span>
        </div>

        {/* Column headers */}
        <div className="flex items-center gap-3 border-b border-border/50 px-5 py-2">
          <span className="type-table-header w-40 shrink-0">Feature</span>
          <span className="type-table-header flex-1">Agent</span>
          <span className="type-table-header w-28 shrink-0">Model</span>
          <span className="type-table-header w-16 shrink-0 text-right">Cost</span>
          <span className="type-table-header w-12 shrink-0 text-right">Turns</span>
          <span className="type-table-header w-16 shrink-0 text-right">Time</span>
          <span className="type-table-header w-20 shrink-0 text-right">Tokens</span>
        </div>

        {/* Rows */}
        <div>
          {runData.map((r: RunRow) => {
            const model = r.models?.split(",")[0] ?? "";
            const mColor = getModelColor(model);
            return (
              <div
                key={r.id}
                className="flex items-center gap-3 border-b border-border/20 px-5 py-2.5 transition-colors hover:bg-bg-elevated/50"
              >
                <span className="w-40 shrink-0 truncate text-[12px] text-text-secondary">
                  {r.feature}
                </span>
                <span className="min-w-0 flex-1 truncate text-[13px] text-text">
                  {r.agentType}
                </span>
                <span className="w-28 shrink-0">
                  <span
                    className="type-badge rounded-full px-2 py-0.5"
                    style={{
                      color: mColor,
                      backgroundColor: mColor + "18",
                    }}
                  >
                    {shortModel(model)}
                  </span>
                </span>
                <span
                  className="w-16 shrink-0 text-right text-[13px] font-medium tabular-nums text-accent"
                  style={{ fontFamily: "var(--font-mono)" }}
                >
                  {formatCost(r.totalCostUsd ?? 0)}
                </span>
                <span
                  className="w-12 shrink-0 text-right text-[12px] tabular-nums text-text-secondary"
                  style={{ fontFamily: "var(--font-mono)" }}
                >
                  {r.numTurns}
                </span>
                <span
                  className="w-16 shrink-0 text-right text-[12px] tabular-nums text-text-tertiary"
                  style={{ fontFamily: "var(--font-mono)" }}
                >
                  {r.durationMs ? formatDuration(r.durationMs) : "—"}
                </span>
                <span
                  className="w-20 shrink-0 text-right text-[11px] tabular-nums text-text-tertiary"
                  style={{ fontFamily: "var(--font-mono)" }}
                >
                  {formatTokens((r.inputTokens ?? 0) + (r.outputTokens ?? 0))}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/* ── Breakdown Panel ───────────────────────────────────────────── */

function BreakdownPanel({
  title,
  data,
  maxCost,
  colorFn,
}: {
  title: string;
  data: AggRow[];
  maxCost: number;
  colorFn: (row: AggRow, i: number) => string;
}) {
  return (
    <div className="surface p-5">
      <span className="type-section-header">{title}</span>
      <div className="mt-4 space-y-2.5">
        {data.map((row, i) => {
          const pct = maxCost > 0 ? (row.totalCostUsd / maxCost) * 100 : 0;
          const color = colorFn(row, i);
          return (
            <div key={row.groupKey}>
              <div className="mb-1 flex items-baseline justify-between">
                <span className="min-w-0 truncate text-[12px] text-text-secondary">
                  {shortLabel(row.groupKey)}
                </span>
                <div className="flex shrink-0 items-baseline gap-2">
                  <span className="type-caption">{row.runCount} runs</span>
                  <span
                    className="text-[12px] font-medium tabular-nums"
                    style={{ fontFamily: "var(--font-mono)", color }}
                  >
                    {formatCost(row.totalCostUsd)}
                  </span>
                </div>
              </div>
              <div
                className="h-1.5 rounded-full"
                style={{ backgroundColor: "rgba(255,255,255,0.04)" }}
              >
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{
                    width: `${Math.max(pct, 2)}%`,
                    backgroundColor: color,
                  }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ── Sub-components ────────────────────────────────────────────── */

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

/* ── Helpers ───────────────────────────────────────────────────── */

function shortLabel(key: string): string {
  // Shorten model IDs in breakdown panels
  if (key.includes("/") || key.includes("-")) return shortModel(key);
  return key;
}
