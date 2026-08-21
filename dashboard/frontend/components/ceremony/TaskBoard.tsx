"use client";

import React, { useState, useMemo, useCallback } from "react";
import {
  Shield,
  Check,
  Lock,
  AlertTriangle,
  Plus,
} from "lucide-react";
import type {
  ArchitectTask,
  GateResult,
} from "@/lib/graphql/queries/ceremony-editor";

// ── Phase computation ──────────────────────────────────────────

interface Phase {
  label: string;
  depth: number;
  tasks: ArchitectTask[];
}

function computePhases(tasks: ArchitectTask[]): Phase[] {
  const idSet = new Set(tasks.map((t) => t.id));
  const depthMap = new Map<string, number>();

  function getDepth(id: string, visited: Set<string>): number {
    if (depthMap.has(id)) return depthMap.get(id)!;
    if (visited.has(id)) return 0;
    visited.add(id);
    const t = tasks.find((x) => x.id === id);
    if (!t || t.dependsOn.length === 0) { depthMap.set(id, 0); return 0; }
    const d = Math.max(...t.dependsOn.filter((x) => idSet.has(x)).map((x) => getDepth(x, visited))) + 1;
    depthMap.set(id, d);
    return d;
  }

  tasks.forEach((t) => getDepth(t.id, new Set()));
  const max = Math.max(0, ...depthMap.values());
  const phases: Phase[] = [];
  for (let d = 0; d <= max; d++) {
    const pt = tasks.filter((t) => (depthMap.get(t.id) ?? 0) === d);
    if (!pt.length) continue;
    const label = d === 0 ? "Start" : d === max && max > 0 ? "Integration" : `Phase ${d}`;
    phases.push({ label, depth: d, tasks: pt });
  }
  return phases;
}

// ── Critical path ──────────────────────────────────────────────

function computeCriticalPath(tasks: ArchitectTask[]): Set<string> {
  const memo = new Map<string, string[]>();
  function longest(id: string): string[] {
    if (memo.has(id)) return memo.get(id)!;
    const ds = tasks.filter((x) => x.dependsOn.includes(id));
    if (ds.length === 0) { memo.set(id, [id]); return [id]; }
    let best: string[] = [];
    for (const d of ds) {
      const p = longest(d.id);
      if (p.length > best.length) best = p;
    }
    const result = [id, ...best];
    memo.set(id, result);
    return result;
  }
  const roots = tasks.filter((t) => t.dependsOn.length === 0);
  let critical: string[] = [];
  for (const r of roots) {
    const p = longest(r.id);
    if (p.length > critical.length) critical = p;
  }
  return new Set(critical);
}

// ── Dep distance (BFS) ────────────────────────────────────────

function computeDepDistances(taskId: string, tasks: ArchitectTask[]) {
  const upDist = new Map<string, number>();
  let queue: { id: string; dist: number }[] = [{ id: taskId, dist: 0 }];
  const visited = new Set([taskId]);
  while (queue.length) {
    const { id, dist } = queue.shift()!;
    const t = tasks.find((x) => x.id === id);
    if (!t) continue;
    for (const depId of t.dependsOn) {
      if (!visited.has(depId)) {
        visited.add(depId);
        upDist.set(depId, dist + 1);
        queue.push({ id: depId, dist: dist + 1 });
      }
    }
  }
  const downDist = new Map<string, number>();
  queue = [{ id: taskId, dist: 0 }];
  const visited2 = new Set([taskId]);
  while (queue.length) {
    const { id, dist } = queue.shift()!;
    for (const t of tasks) {
      if (t.dependsOn.includes(id) && !visited2.has(t.id)) {
        visited2.add(t.id);
        downDist.set(t.id, dist + 1);
        queue.push({ id: t.id, dist: dist + 1 });
      }
    }
  }
  return { upDist, downDist };
}

// ── Inline code renderer ───────────────────────────────────────

function renderInline(text: string): React.ReactNode {
  const parts = text.split(/(`[^`]+`)/g);
  if (parts.length === 1) return text;
  return parts.map((part, i) => {
    if (part.startsWith("`") && part.endsWith("`")) {
      return (
        <code
          key={i}
          style={{
            fontFamily: "var(--font-mono)", fontSize: 11,
            color: "var(--color-accent)", background: "var(--color-accent-dim)",
            padding: "2px 5px", borderRadius: 3,
          }}
        >
          {part.slice(1, -1)}
        </code>
      );
    }
    return part;
  });
}

// ── Structured text renderer ───────────────────────────────────

function StructuredBody({ text }: { text: string }) {
  const lines = text.split("\n");
  const els: React.ReactNode[] = [];
  let key = 0;

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) { els.push(<div key={key++} style={{ height: 10 }} />); continue; }
    const numMatch = trimmed.match(/^(\d+)\.\s+(.+)/);
    if (numMatch) {
      els.push(
        <div key={key++} style={{ display: "flex", gap: 8, padding: "3px 0", fontSize: 12, lineHeight: 1.7, color: "var(--color-text-secondary)" }}>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--color-text-tertiary)", minWidth: 14, textAlign: "right", marginTop: 2 }}>{numMatch[1]}.</span>
          <span>{renderInline(numMatch[2])}</span>
        </div>,
      );
    } else if (trimmed.startsWith("- ")) {
      els.push(
        <div key={key++} style={{ display: "flex", gap: 8, padding: "3px 0", fontSize: 12, lineHeight: 1.7, color: "var(--color-text-secondary)" }}>
          <span style={{ color: "var(--color-text-tertiary)", marginTop: 2 }}>&bull;</span>
          <span>{renderInline(trimmed.slice(2))}</span>
        </div>,
      );
    } else {
      els.push(
        <div key={key++} style={{ fontSize: 12, lineHeight: 1.7, color: "var(--color-text-secondary)", padding: "1px 0" }}>
          {renderInline(trimmed)}
        </div>,
      );
    }
  }
  return <>{els}</>;
}

// ── Filename helper ────────────────────────────────────────────

function filename(path: string): string {
  return path.split("/").pop() ?? path;
}

// ── Execution Shape ────────────────────────────────────────────

function ExecutionShape({
  phases,
  tasks,
  selectedId,
  onSelect,
}: {
  phases: Phase[];
  tasks: ArchitectTask[];
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  const maxTasks = Math.max(...phases.map((p) => p.tasks.length));
  const depInfo = useMemo(() => computeDepDistances(selectedId, tasks), [selectedId, tasks]);

  return (
    <div className="surface" style={{ padding: "14px 16px 16px", marginTop: 20 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 9, fontWeight: 500, color: "var(--color-text-tertiary)", textTransform: "uppercase", letterSpacing: "0.04em" }}>
          Execution Shape
        </span>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 9, color: "var(--color-text-tertiary)" }}>
          {phases.length} sequential steps · {maxTasks} can run at once
        </span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2, maxWidth: 360, margin: "0 auto" }}>
        {phases.map((phase) => {
          const widthPct = (phase.tasks.length / maxTasks) * 100;
          return (
            <div key={phase.depth} style={{ display: "flex", gap: 2, width: `${widthPct}%`, justifyContent: "center" }}>
              {phase.tasks.map((t) => {
                const isSel = selectedId === t.id;
                const upDist = depInfo.upDist.get(t.id);
                const downDist = depInfo.downDist.get(t.id);

                let bg = "var(--color-bg-elevated)";
                let color = "var(--color-text-tertiary)";
                let border = "1px solid var(--color-border)";

                if (isSel) {
                  bg = "var(--color-accent-dim)";
                  color = "var(--color-accent)";
                  border = "1px solid var(--color-accent)";
                } else if (upDist != null) {
                  const d = Math.min(upDist, 3);
                  const opacity = [0.14, 0.08, 0.04][d - 1] ?? 0.04;
                  const bOpacity = [0.2, 0.12, 0.08][d - 1] ?? 0.08;
                  bg = `rgba(139,92,246,${opacity})`;
                  color = `rgba(139,92,246,${d <= 2 ? 1 : 0.6})`;
                  border = `1px solid rgba(139,92,246,${bOpacity})`;
                } else if (downDist != null) {
                  const d = Math.min(downDist, 3);
                  const opacity = [0.14, 0.08, 0.04][d - 1] ?? 0.04;
                  const bOpacity = [0.2, 0.12, 0.08][d - 1] ?? 0.08;
                  bg = `rgba(68,204,119,${opacity})`;
                  color = `rgba(68,204,119,${d <= 2 ? 1 : 0.6})`;
                  border = `1px solid rgba(68,204,119,${bOpacity})`;
                }

                return (
                  <span
                    key={t.id}
                    onClick={() => onSelect(t.id)}
                    title={t.title}
                    style={{
                      flex: 1, maxWidth: 72, minWidth: 36, height: 24,
                      display: "flex", alignItems: "center", justifyContent: "center",
                      borderRadius: 4, cursor: "pointer", transition: "all 150ms",
                      fontFamily: "var(--font-mono)", fontSize: 9, fontWeight: 500,
                      background: bg, color, border,
                    }}
                  >
                    T{t.id}
                  </span>
                );
              })}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Task Row ───────────────────────────────────────────────────

function TaskRow({
  task,
  tasks,
  selected,
  onSelect,
}: {
  task: ArchitectTask;
  tasks: ArchitectTask[];
  selected: boolean;
  onSelect: () => void;
}) {
  const isOpus = task.agentModel === "opus";
  const downstream = tasks.filter((t) => t.dependsOn.includes(task.id));

  return (
    <div
      onClick={onSelect}
      style={{
        display: "flex", alignItems: "center", gap: 10,
        padding: "7px 12px", cursor: "pointer",
        transition: "background 120ms",
        borderLeft: selected ? "2px solid var(--color-accent)" : "2px solid transparent",
        background: selected ? "var(--color-bg-card)" : "transparent",
      }}
      onMouseEnter={(e) => { if (!selected) e.currentTarget.style.background = "var(--color-bg-card)"; }}
      onMouseLeave={(e) => { if (!selected) e.currentTarget.style.background = "transparent"; }}
    >
      {/* ID */}
      <span style={{
        fontFamily: "var(--font-mono)", fontSize: 10, fontWeight: 600, width: 24, flexShrink: 0,
        color: selected || isOpus ? "var(--color-accent)" : "var(--color-text-tertiary)",
      }}>
        T{task.id}
      </span>

      {/* Title */}
      <span style={{
        fontSize: 12, fontWeight: 500, color: "var(--color-text)",
        flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
      }}>
        {task.title}
      </span>

      {/* Primary file + overflow */}
      <span style={{ display: "flex", gap: 3, flexShrink: 0, alignItems: "center" }}>
        {task.filesTouched.length > 0 && (
          <span style={{
            fontFamily: "var(--font-mono)", fontSize: 9, color: "var(--color-text-tertiary)",
            padding: "1px 5px", borderRadius: 3,
            background: "var(--color-bg-elevated)", border: "1px solid var(--color-border-light)",
          }}>
            {filename(task.filesTouched[0])}
          </span>
        )}
        {task.filesTouched.length > 1 && (
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 9, color: "var(--color-text-tertiary)" }}>
            +{task.filesTouched.length - 1}
          </span>
        )}
      </span>

      {/* Model */}
      <span style={{
        fontFamily: "var(--font-mono)", fontSize: 9, fontWeight: 500, flexShrink: 0,
        padding: "1px 5px", borderRadius: 3, textTransform: "uppercase", letterSpacing: "0.03em",
        color: isOpus ? "var(--color-accent)" : "var(--color-text-tertiary)",
        background: isOpus ? "var(--color-accent-dim)" : "rgba(85,85,106,0.08)",
      }}>
        {task.agentModel}
      </span>

      {/* Dep flow */}
      <span style={{ fontFamily: "var(--font-mono)", fontSize: 9, color: "var(--color-text-tertiary)", flexShrink: 0, textAlign: "right", minWidth: 60 }}>
        {task.dependsOn.length > 0 && (
          <span style={{ color: "var(--color-violet)" }}>← {task.dependsOn.map((d) => `T${d}`).join(",")}</span>
        )}
        {task.dependsOn.length > 0 && downstream.length > 0 && " "}
        {downstream.length > 0 && (
          <span>→ {downstream.map((d) => `T${d.id}`).join(",")}</span>
        )}
      </span>
    </div>
  );
}

// ── Detail Panel ───────────────────────────────────────────────

function TaskDetail({
  task,
  tasks,
  onSelect,
}: {
  task: ArchitectTask;
  tasks: ArchitectTask[];
  onSelect: (id: string) => void;
}) {
  const isOpus = task.agentModel === "opus";
  const depTasks = task.dependsOn.map((id) => tasks.find((t) => t.id === id)).filter(Boolean) as ArchitectTask[];
  const downstream = tasks.filter((t) => t.dependsOn.includes(task.id));

  return (
    <div style={{ padding: "20px 24px" }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
        <span style={{
          fontFamily: "var(--font-mono)", fontSize: 11, fontWeight: 600,
          padding: "2px 7px", borderRadius: 4,
          color: isOpus ? "var(--color-bg)" : "var(--color-accent)",
          background: isOpus ? "var(--color-accent)" : "var(--color-accent-dim)",
        }}>
          T{task.id}
        </span>
        <span style={{
          fontFamily: "var(--font-mono)", fontSize: 9, fontWeight: 500, textTransform: "uppercase",
          letterSpacing: "0.03em", padding: "2px 6px", borderRadius: 3,
          color: isOpus ? "var(--color-accent)" : "var(--color-text-tertiary)",
          background: isOpus ? "var(--color-accent-dim)" : "rgba(85,85,106,0.08)",
        }}>
          {task.agentModel}
        </span>
      </div>

      {/* Title */}
      <div style={{ fontSize: 15, fontWeight: 600, color: "var(--color-text)", lineHeight: 1.4, marginBottom: 20 }}>
        {task.title}
      </div>

      {/* What — Description */}
      <Section label="What">
        <StructuredBody text={task.description} />
      </Section>

      {/* Why — Rationale */}
      {task.rationale && (
        <Section label="Why">
          <div style={{
            fontSize: 12, lineHeight: 1.7, color: "var(--color-text-secondary)",
            padding: "10px 12px", borderRadius: 6,
            background: "var(--color-bg-card)", border: "1px solid var(--color-border-light)",
          }}>
            {renderInline(task.rationale)}
          </div>
        </Section>
      )}

      {/* Files */}
      <Section label="Files">
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {task.filesTouched.map((f) => (
            <div key={f} style={{
              fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--color-text-secondary)",
              padding: "4px 8px", borderRadius: 4,
              background: "var(--color-bg-card)", border: "1px solid var(--color-border-light)",
            }}>
              {f}
            </div>
          ))}
        </div>
      </Section>

      {/* Done when — Acceptance criteria */}
      {task.acceptanceCriteria && (
        <Section label="Done when">
          {task.acceptanceCriteria.split("\n").map((line, i) => {
            const trimmed = line.trim();
            if (!trimmed) return null;
            const text = trimmed.startsWith("- ") ? trimmed.slice(2) : trimmed;
            return (
              <div key={i} style={{ display: "flex", gap: 8, padding: "4px 0", fontSize: 12, lineHeight: 1.6, color: "var(--color-text-secondary)" }}>
                <span style={{ color: "var(--color-text-tertiary)", flexShrink: 0, marginTop: 2, fontSize: 11 }}>☐</span>
                <span>{renderInline(text)}</span>
              </div>
            );
          })}
        </Section>
      )}

      <div style={{ height: 1, background: "var(--color-border-light)", margin: "16px 0" }} />

      {/* Connected to */}
      {(depTasks.length > 0 || downstream.length > 0) && (
        <Section label="Connected to">
          {depTasks.map((d) => (
            <DepRow key={d.id} task={d} direction="up" onClick={() => onSelect(d.id)} />
          ))}
          {downstream.map((d) => (
            <DepRow key={d.id} task={d} direction="down" onClick={() => onSelect(d.id)} />
          ))}
        </Section>
      )}

      {/* Assumptions */}
      {task.assumptions && task.assumptions.length > 0 && (
        <Section label="Assumptions">
          {task.assumptions.map((a, i) => (
            <div key={i} style={{ display: "flex", gap: 6, padding: "4px 0", fontSize: 11, lineHeight: 1.5, color: "var(--color-amber)" }}>
              <span style={{ flexShrink: 0, marginTop: 2, fontSize: 10 }}>⚑</span>
              <span>{renderInline(a)}</span>
            </div>
          ))}
        </Section>
      )}
    </div>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{
        fontFamily: "var(--font-mono)", fontSize: 9, fontWeight: 500,
        color: "var(--color-text-tertiary)", textTransform: "uppercase",
        letterSpacing: "0.04em", marginBottom: 8,
      }}>
        {label}
      </div>
      {children}
    </div>
  );
}

function DepRow({ task, direction, onClick }: { task: ArchitectTask; direction: "up" | "down"; onClick: () => void }) {
  return (
    <div
      onClick={onClick}
      style={{
        display: "flex", alignItems: "center", gap: 6,
        padding: "4px 8px", margin: "2px 0", borderRadius: 4,
        cursor: "pointer", transition: "background 120ms",
        fontSize: 11, color: "var(--color-text-secondary)",
      }}
      onMouseEnter={(e) => { e.currentTarget.style.background = "var(--color-bg-card-hover)"; }}
      onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
    >
      <span style={{ fontFamily: "var(--font-mono)", fontSize: 9, color: "var(--color-text-tertiary)" }}>
        {direction === "up" ? "←" : "→"}
      </span>
      <span style={{
        fontFamily: "var(--font-mono)", fontSize: 10, fontWeight: 600,
        color: direction === "up" ? "var(--color-violet)" : "var(--color-emerald)",
      }}>
        T{task.id}
      </span>
      <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {task.title}
      </span>
    </div>
  );
}

// ── Main TaskBoard ─────────────────────────────────────────────

export interface TaskBoardProps {
  tasks: ArchitectTask[];
  featureName: string;
  intent?: string;
  gate?: GateResult | null;
  onVerify?: () => void;
  onApprove?: () => void;
  approved?: boolean;
  verifying?: boolean;
}

export function TaskBoard({
  tasks,
  featureName,
  intent,
  gate,
  onVerify,
  onApprove,
  approved = false,
  verifying = false,
}: TaskBoardProps) {
  const [selectedId, setSelectedId] = useState<string>(tasks[0]?.id ?? "");

  const phases = useMemo(() => computePhases(tasks), [tasks]);
  const totalFiles = useMemo(() => new Set(tasks.flatMap((t) => t.filesTouched)).size, [tasks]);
  const roots = phases.length > 0 ? phases[0].tasks.length : 0;
  const selectedTask = tasks.find((t) => t.id === selectedId) ?? null;

  const handleSelect = useCallback((id: string) => {
    if (id && id !== selectedId) setSelectedId(id);
  }, [selectedId]);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      {/* Content row */}
      <div style={{ flex: 1, display: "flex", overflow: "hidden", minHeight: 0 }}>

      {/* Left: Plan document */}
      <div style={{ flex: "1 1 0", overflowY: "auto", padding: "24px 32px 24px", minWidth: 420, maxWidth: 860 }}>
        {/* Header */}
        <div style={{ marginBottom: 24 }}>
          {/* Mode badge */}
          <div style={{
            display: "inline-flex", alignItems: "center", gap: 6,
            fontFamily: "var(--font-mono)", fontSize: 9, fontWeight: 500,
            color: "var(--color-accent)", textTransform: "uppercase", letterSpacing: "0.06em",
            padding: "3px 8px", borderRadius: 4,
            background: "var(--color-accent-dim)", border: "1px solid var(--color-accent-glow)",
            marginBottom: 12,
          }}>
            <span style={{ width: 5, height: 5, borderRadius: "50%", background: "var(--color-accent)" }} />
            Plan · Decomposition
          </div>

          {/* Feature name */}
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 18, fontWeight: 600, color: "var(--color-text)", lineHeight: 1.3 }}>
            {featureName}
          </div>

          {/* Intent */}
          {intent && (
            <div style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.5, marginTop: 6, maxWidth: 600 }}>
              {intent}
            </div>
          )}

          {/* Stats */}
          <div style={{ display: "flex", gap: 24, marginTop: 16 }}>
            <PlanStat value={tasks.length} label="tasks" />
            <PlanStat value={totalFiles} label="files" />
            <PlanStat value={phases.length} label="depth" />
            <PlanStat value={roots} label="parallel" />
          </div>

          {/* Gate warnings */}
          {gate && gate.warnings.length > 0 && (
            <div style={{
              marginTop: 16, padding: "10px 14px", borderRadius: 8,
              background: "rgba(240,178,50,0.04)", border: "1px solid rgba(240,178,50,0.1)",
            }}>
              {gate.warnings.map((w, i) => (
                <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 8, padding: "3px 0", fontSize: 12, color: "var(--color-amber)" }}>
                  <AlertTriangle size={11} style={{ flexShrink: 0, marginTop: 3 }} />
                  {w}
                </div>
              ))}
            </div>
          )}

          {/* Execution shape */}
          <ExecutionShape phases={phases} tasks={tasks} selectedId={selectedId} onSelect={handleSelect} />
        </div>

        {/* Task rows by phase */}
        {phases.map((phase) => (
          <div key={phase.depth} style={{ marginTop: phase.depth === 0 ? 0 : 24 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
              <span style={{
                fontFamily: "var(--font-mono)", fontSize: 11, fontWeight: 600,
                color: "var(--color-text-tertiary)", textTransform: "uppercase", letterSpacing: "0.04em",
              }}>
                {phase.label}
              </span>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--color-text-tertiary)" }}>
                {phase.tasks.length} task{phase.tasks.length > 1 ? "s" : ""}
              </span>
              <span style={{ flex: 1, height: 1, background: "var(--color-border-light)" }} />
            </div>
            {phase.tasks.map((t) => (
              <TaskRow key={t.id} task={t} tasks={tasks} selected={selectedId === t.id} onSelect={() => handleSelect(t.id)} />
            ))}
            {!approved && (
              <button
                style={{
                  display: "flex", alignItems: "center", gap: 6,
                  padding: "5px 12px 5px 46px",
                  fontSize: 10, fontWeight: 500, color: "var(--color-text-tertiary)",
                  background: "transparent", border: "none", cursor: "pointer",
                }}
                onMouseEnter={(e) => { e.currentTarget.style.color = "var(--color-text-secondary)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.color = "var(--color-text-tertiary)"; }}
              >
                <Plus size={10} /> Add task
              </button>
            )}
          </div>
        ))}
      </div>

      {/* Right: Detail panel */}
      <div style={{
        flex: "1 1 480px", minWidth: 360, maxWidth: 640,
        borderLeft: "1px solid var(--color-border)",
        background: "var(--color-bg-elevated)",
        overflowY: "auto",
      }}>
        {selectedTask ? (
          <TaskDetail task={selectedTask} tasks={tasks} onSelect={handleSelect} />
        ) : (
          <div style={{
            display: "flex", flexDirection: "column", alignItems: "center",
            justifyContent: "center", height: "100%", gap: 8,
            color: "var(--color-text-tertiary)", fontSize: 12, textAlign: "center", padding: 40,
          }}>
            {tasks.length === 0 ? (
              <>
                <div style={{ fontSize: 24, opacity: 0.4 }}>⑆</div>
                <div>No tasks generated</div>
                <div style={{ fontSize: 11 }}>Try refining the spec or using a different model.</div>
              </>
            ) : (
              <div style={{ fontSize: 11 }}>Select a task to view details</div>
            )}
          </div>
        )}
      </div>

      </div>{/* end content row */}

      {/* Bottom bar */}
      <div style={{
        flexShrink: 0,
        display: "flex", alignItems: "center", gap: 12,
        padding: "10px 24px",
        background: "var(--color-bg-card)",
        borderTop: "1px solid var(--color-border)",
      }}>
        {/* Status indicators */}
        {gate && (
          <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "var(--color-text-secondary)" }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: gate.warnings.length > 0 ? "var(--color-amber)" : "var(--color-emerald)" }} />
            {gate.warnings.length > 0 ? `${gate.warnings.length} warnings` : "No warnings"}
          </div>
        )}
        {approved && (
          <div style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12, color: "var(--color-emerald)" }}>
            <Lock size={11} /> Approved
          </div>
        )}

        <span style={{ flex: 1 }} />

        {!approved && onVerify && (
          <button
            onClick={onVerify}
            disabled={verifying}
            style={{
              display: "inline-flex", alignItems: "center", gap: 6,
              padding: "6px 14px", fontSize: 11, fontWeight: 500, borderRadius: 6,
              color: verifying ? "var(--color-text-tertiary)" : "var(--color-text-secondary)",
              background: "var(--color-bg-elevated)", border: "1px solid var(--color-border)",
              cursor: verifying ? "default" : "pointer",
            }}
          >
            <Shield size={11} /> {verifying ? "Verifying..." : "Verify"}
          </button>
        )}
        {!approved && onApprove && (
          <button
            onClick={onApprove}
            style={{
              display: "inline-flex", alignItems: "center", gap: 6,
              padding: "8px 20px", fontSize: 12, fontWeight: 600, borderRadius: 6,
              color: "var(--color-bg)", background: "var(--color-accent)",
              border: "1px solid transparent", cursor: "pointer",
            }}
          >
            <Check size={12} /> Approve Plan
          </button>
        )}
      </div>
    </div>
  );
}

// ── Stat helper ────────────────────────────────────────────────

function PlanStat({ value, label }: { value: number; label: string }) {
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: 5 }}>
      <span style={{ fontFamily: "var(--font-mono)", fontSize: 22, fontWeight: 600, color: "var(--color-accent)", lineHeight: 1.1 }}>
        {value}
      </span>
      <span style={{ fontSize: 11, fontWeight: 500, color: "var(--color-text-secondary)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
        {label}
      </span>
    </div>
  );
}
