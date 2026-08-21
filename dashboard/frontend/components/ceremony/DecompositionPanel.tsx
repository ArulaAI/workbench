"use client";

import React, { useState, useMemo } from "react";
import {
  ChevronDown,
  AlertTriangle,
  X,
  GitBranch,
  FileCode,
  ArrowRight,
  Layers,
} from "lucide-react";
import type {
  DecompositionResult,
  ArchitectTask,
  GateResult,
  DecompositionProgressEvent,
} from "@/lib/graphql/queries/ceremony-editor";

// ── DAG phase computation ──────────────────────────────────────

interface PhaseGroup {
  phase: number;
  label: string;
  tasks: ArchitectTask[];
}

function computePhases(tasks: ArchitectTask[]): PhaseGroup[] {
  const idSet = new Set(tasks.map((t) => t.id));
  const depthMap = new Map<string, number>();

  function getDepth(taskId: string, visited: Set<string>): number {
    if (depthMap.has(taskId)) return depthMap.get(taskId)!;
    if (visited.has(taskId)) return 0; // cycle guard
    visited.add(taskId);

    const task = tasks.find((t) => t.id === taskId);
    if (!task || task.dependsOn.length === 0) {
      depthMap.set(taskId, 0);
      return 0;
    }

    const parentDepths = task.dependsOn
      .filter((d) => idSet.has(d))
      .map((d) => getDepth(d, visited));
    const depth = parentDepths.length > 0 ? Math.max(...parentDepths) + 1 : 0;
    depthMap.set(taskId, depth);
    return depth;
  }

  for (const t of tasks) getDepth(t.id, new Set());

  const maxDepth = Math.max(0, ...Array.from(depthMap.values()));
  const groups: PhaseGroup[] = [];

  for (let d = 0; d <= maxDepth; d++) {
    const phaseTasks = tasks.filter((t) => (depthMap.get(t.id) ?? 0) === d);
    if (phaseTasks.length === 0) continue;

    let label: string;
    if (d === 0) {
      label = phaseTasks.length > 1 ? "Parallel roots" : "Root";
    } else if (d === maxDepth && maxDepth > 0) {
      label = "Final integration";
    } else {
      label = `Phase ${d}`;
    }

    groups.push({ phase: d, label, tasks: phaseTasks });
  }

  return groups;
}

// ── Lightweight markdown-ish renderer ───────────────────────────
// Handles newlines, bullet lists, `code spans`, and ```code blocks```
// without pulling in a full markdown library.

function StructuredText({ text }: { text: string }) {
  const lines = text.split("\n");
  const elements: React.ReactNode[] = [];
  let inCodeBlock = false;
  let codeLines: string[] = [];
  let key = 0;

  const flushCode = () => {
    if (codeLines.length > 0) {
      elements.push(
        <pre
          key={key++}
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            lineHeight: 1.5,
            color: "var(--color-text-secondary)",
            background: "var(--color-bg-card)",
            border: "1px solid var(--color-border-light)",
            borderRadius: 4,
            padding: "6px 8px",
            margin: "4px 0",
            overflowX: "auto",
            whiteSpace: "pre-wrap",
          }}
        >
          {codeLines.join("\n")}
        </pre>,
      );
      codeLines = [];
    }
  };

  for (const line of lines) {
    if (line.startsWith("```")) {
      if (inCodeBlock) {
        flushCode();
        inCodeBlock = false;
      } else {
        inCodeBlock = true;
      }
      continue;
    }

    if (inCodeBlock) {
      codeLines.push(line);
      continue;
    }

    const trimmed = line.trim();
    if (!trimmed) {
      elements.push(<div key={key++} style={{ height: 6 }} />);
      continue;
    }

    // Numbered list item
    const numMatch = trimmed.match(/^(\d+)\.\s+(.+)/);
    if (numMatch) {
      elements.push(
        <div
          key={key++}
          style={{
            display: "flex",
            gap: 6,
            padding: "1px 0",
            fontSize: 12,
            lineHeight: 1.5,
            color: "var(--color-text-secondary)",
          }}
        >
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              color: "var(--color-text-tertiary)",
              minWidth: 14,
              textAlign: "right",
              flexShrink: 0,
              marginTop: 2,
            }}
          >
            {numMatch[1]}.
          </span>
          <span>{renderInlineCode(numMatch[2])}</span>
        </div>,
      );
      continue;
    }

    // Bullet
    if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
      elements.push(
        <div
          key={key++}
          style={{
            display: "flex",
            gap: 6,
            padding: "1px 0",
            fontSize: 12,
            lineHeight: 1.5,
            color: "var(--color-text-secondary)",
          }}
        >
          <span
            style={{
              color: "var(--color-text-tertiary)",
              flexShrink: 0,
              marginTop: 1,
            }}
          >
            &bull;
          </span>
          <span>{renderInlineCode(trimmed.slice(2))}</span>
        </div>,
      );
      continue;
    }

    // Heading
    if (trimmed.startsWith("## ") || trimmed.startsWith("### ")) {
      const headingText = trimmed.replace(/^#+\s+/, "");
      elements.push(
        <div
          key={key++}
          style={{
            fontSize: 11,
            fontWeight: 600,
            color: "var(--color-text)",
            marginTop: 6,
            marginBottom: 2,
          }}
        >
          {headingText}
        </div>,
      );
      continue;
    }

    // Regular line
    elements.push(
      <div
        key={key++}
        style={{
          fontSize: 12,
          lineHeight: 1.5,
          color: "var(--color-text-secondary)",
          padding: "1px 0",
        }}
      >
        {renderInlineCode(trimmed)}
      </div>,
    );
  }

  flushCode(); // flush any trailing code block
  return <>{elements}</>;
}

/** Render `backtick` spans as styled inline code */
function renderInlineCode(text: string): React.ReactNode {
  const parts = text.split(/(`[^`]+`)/g);
  if (parts.length === 1) return text;
  return parts.map((part, i) => {
    if (part.startsWith("`") && part.endsWith("`")) {
      return (
        <code
          key={i}
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            color: "var(--color-accent)",
            background: "var(--color-accent-dim)",
            padding: "1px 4px",
            borderRadius: 3,
          }}
        >
          {part.slice(1, -1)}
        </code>
      );
    }
    return part;
  });
}

// ── Task card ──────────────────────────────────────────────────

function TaskCard({
  task,
  allTasks,
}: {
  task: ArchitectTask;
  allTasks: ArchitectTask[];
}) {
  const [expanded, setExpanded] = useState(false);

  const depTasks = task.dependsOn
    .map((id) => allTasks.find((t) => t.id === id))
    .filter(Boolean) as ArchitectTask[];

  // Split description: first paragraph = summary, rest = detail
  const descParts = useMemo(() => {
    if (!task.description) return { summary: "", detail: "" };
    // Split on double-newline (paragraph break)
    const idx = task.description.indexOf("\n\n");
    if (idx === -1) return { summary: task.description, detail: "" };
    return {
      summary: task.description.slice(0, idx),
      detail: task.description.slice(idx + 2),
    };
  }, [task.description]);

  return (
    <div
      style={{
        background: "var(--color-bg-elevated)",
        border: "1px solid var(--color-border)",
        borderRadius: 8,
        boxShadow: "0 1px 2px rgba(0,0,0,0.2)",
        overflow: "hidden",
      }}
    >
      {/* Header bar: ID + title + deps */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "8px 12px",
          background: "var(--color-bg-card)",
          borderBottom: "1px solid var(--color-border-light)",
          cursor: "pointer",
        }}
        onClick={() => setExpanded(!expanded)}
      >
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            fontWeight: 600,
            color: "var(--color-accent)",
            flexShrink: 0,
          }}
        >
          T{task.id}
        </span>
        <span
          style={{
            fontSize: 12,
            fontWeight: 600,
            color: "var(--color-text)",
            flex: 1,
            minWidth: 0,
          }}
        >
          {task.title}
        </span>

        {/* File count */}
        {task.filesTouched.length > 0 && (
          <span
            className="type-compact-label"
            style={{
              color: "var(--color-text-tertiary)",
              display: "flex",
              alignItems: "center",
              gap: 3,
              flexShrink: 0,
            }}
          >
            <FileCode size={9} />
            {task.filesTouched.length}
          </span>
        )}

        {/* Dependency badges */}
        {depTasks.length > 0 && (
          <span
            className="type-compact-label"
            style={{
              color: "var(--color-violet)",
              display: "flex",
              alignItems: "center",
              gap: 3,
              flexShrink: 0,
            }}
          >
            <ArrowRight size={9} />
            {depTasks.map((d) => `T${d.id}`).join(", ")}
          </span>
        )}

        <ChevronDown
          size={11}
          style={{
            color: "var(--color-text-tertiary)",
            flexShrink: 0,
            transform: expanded ? "rotate(0deg)" : "rotate(-90deg)",
            transition: "transform 150ms",
          }}
        />
      </div>

      {/* Summary line — always visible */}
      <div style={{ padding: "8px 12px" }}>
        {descParts.summary && (
          <div style={{ fontSize: 12, lineHeight: 1.5, color: "var(--color-text-secondary)" }}>
            {renderInlineCode(descParts.summary)}
          </div>
        )}

        {/* Files — always visible */}
        {task.filesTouched.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 6 }}>
            {task.filesTouched.map((f) => (
              <span
                key={f}
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 10,
                  fontWeight: 400,
                  color: "var(--color-text-secondary)",
                  padding: "2px 6px",
                  borderRadius: 4,
                  background: "var(--color-bg-card)",
                  border: "1px solid var(--color-border-light)",
                }}
              >
                {f}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div
          style={{
            padding: "0 12px 10px",
            display: "flex",
            flexDirection: "column",
            gap: 12,
          }}
        >
          {/* Full description detail */}
          {descParts.detail && (
            <div
              style={{
                padding: "8px 10px",
                background: "var(--color-bg-card)",
                borderRadius: 6,
                border: "1px solid var(--color-border-light)",
              }}
            >
              <StructuredText text={descParts.detail} />
            </div>
          )}

          {/* Acceptance criteria */}
          {task.acceptanceCriteria && (
            <div>
              <div className="type-compact-label" style={{ marginBottom: 4 }}>
                Acceptance Criteria
              </div>
              <StructuredText text={task.acceptanceCriteria} />
            </div>
          )}

          {/* Dependencies */}
          {depTasks.length > 0 && (
            <div>
              <div className="type-compact-label" style={{ marginBottom: 4 }}>
                Depends On
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                {depTasks.map((d) => (
                  <span
                    key={d.id}
                    style={{
                      fontSize: 11,
                      fontWeight: 400,
                      fontFamily: "var(--font-sans)",
                      color: "var(--color-text-secondary)",
                    }}
                  >
                    <span
                      style={{
                        fontFamily: "var(--font-mono)",
                        color: "var(--color-violet)",
                        fontSize: 10,
                        fontWeight: 500,
                      }}
                    >
                      T{d.id}
                    </span>{" "}
                    {d.title}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Gate summary ───────────────────────────────────────────────

function GateSummary({ gate }: { gate: GateResult }) {
  if (gate.warnings.length === 0 && gate.overall === "pass") return null;

  const colorMap: Record<string, string> = {
    pass: "var(--color-emerald)",
    warn: "var(--color-amber)",
    fail: "var(--color-red)",
  };
  const bgMap: Record<string, string> = {
    pass: "rgba(68,204,119,0.06)",
    warn: "rgba(240,178,50,0.06)",
    fail: "rgba(239,68,100,0.06)",
  };

  return (
    <div
      style={{
        padding: "10px 16px",
        background: bgMap[gate.overall] ?? bgMap.warn,
        borderBottom: "1px solid var(--color-border-light)",
      }}
    >
      {gate.warnings.map((w, i) => (
        <div
          key={i}
          style={{
            display: "flex",
            alignItems: "flex-start",
            gap: 8,
            padding: "2px 0",
          }}
        >
          <AlertTriangle
            size={12}
            style={{
              color: colorMap[gate.overall] ?? colorMap.warn,
              flexShrink: 0,
              marginTop: 1,
            }}
          />
          <span className="type-body" style={{ fontSize: 12 }}>
            {w}
          </span>
        </div>
      ))}
    </div>
  );
}

// ── Stage labels ───────────────────────────────────────────────

const STAGE_LABELS: Record<string, string> = {
  loading_specs: "Loading specs",
  assembling_context: "Assembling codebase context",
  calling_architect: "Calling Architect",
  parsing_response: "Parsing response",
  running_gate: "Running decomposition gate",
  complete: "Complete",
  error: "Failed",
};

const STAGE_ORDER = [
  "loading_specs",
  "assembling_context",
  "calling_architect",
  "parsing_response",
  "running_gate",
  "complete",
];

function StageIndicator({ stage }: { stage: string }) {
  const currentIdx = STAGE_ORDER.indexOf(stage);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
      {STAGE_ORDER.slice(0, -1).map((s, i) => {
        const isDone = i < currentIdx;
        const isCurrent = s === stage;
        const isPending = i > currentIdx;
        const isError = stage === "error" && isCurrent;

        return (
          <div
            key={s}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: "5px 0",
            }}
          >
            {/* Dot */}
            <div
              style={{
                width: 8,
                height: 8,
                borderRadius: 4,
                flexShrink: 0,
                background: isDone
                  ? "var(--color-emerald)"
                  : isCurrent
                    ? isError
                      ? "var(--color-red)"
                      : "var(--color-accent)"
                    : "var(--color-border)",
                boxShadow: isCurrent && !isError
                  ? "0 0 6px var(--color-accent-glow)"
                  : "none",
                transition: "all 300ms ease",
              }}
            />
            <span
              style={{
                fontFamily: "var(--font-sans)",
                fontSize: 12,
                fontWeight: isCurrent ? 500 : 400,
                color: isDone
                  ? "var(--color-text-tertiary)"
                  : isCurrent
                    ? "var(--color-text)"
                    : "var(--color-text-tertiary)",
                transition: "color 300ms ease",
              }}
            >
              {STAGE_LABELS[s] ?? s}
              {isCurrent && s === "calling_architect" && (
                <span
                  style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: 10,
                    color: "var(--color-text-tertiary)",
                    marginLeft: 6,
                  }}
                >
                  waiting for response...
                </span>
              )}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ── Progress view ──────────────────────────────────────────────

function DecompositionProgress({
  stage,
  elapsed,
  onCancel,
  error,
}: {
  stage: string;
  elapsed: number;
  onCancel: () => void;
  error?: string | null;
}) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        borderTop: "1px solid var(--color-border)",
        background: "var(--color-bg-card)",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "10px 16px",
          borderBottom: "1px solid var(--color-border-light)",
        }}
      >
        <GitBranch size={14} style={{ color: "var(--color-accent)" }} />
        <span className="type-section-header">Decomposing</span>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            fontWeight: 500,
            color: "var(--color-text-tertiary)",
          }}
        >
          {elapsed}s
        </span>
        <button
          onClick={onCancel}
          style={{
            marginLeft: "auto",
            padding: "3px 10px",
            fontSize: 11,
            fontWeight: 500,
            fontFamily: "var(--font-sans)",
            color: "var(--color-text-secondary)",
            background: "var(--color-bg-elevated)",
            border: "1px solid var(--color-border)",
            borderRadius: 4,
            cursor: "pointer",
          }}
        >
          Cancel
        </button>
      </div>

      <div style={{ padding: "12px 16px 16px" }}>
        <StageIndicator stage={stage} />
        {error && (
          <div
            className="type-body"
            style={{
              marginTop: 8,
              fontSize: 12,
              color: "var(--color-red)",
            }}
          >
            {error}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main panel ─────────────────────────────────────────────────

interface DecompositionPanelProps {
  result: DecompositionResult | null;
  onClose: () => void;
  /** Live progress from subscription */
  progress?: { stage: string; elapsed: number; error?: string | null } | null;
  onCancel?: () => void;
  /** Open the full task board view */
  onOpenBoard?: () => void;
  /** Accept the decomposition and generate child RFC drafts */
  onGenerateChildRfcs?: () => void;
  generatingChildRfcs?: boolean;
}

export function DecompositionPanel({
  result,
  onClose,
  progress,
  onCancel,
  onOpenBoard,
  onGenerateChildRfcs,
  generatingChildRfcs = false,
}: DecompositionPanelProps) {
  const phases = useMemo(
    () => computePhases(result?.tasks ?? []),
    [result?.tasks],
  );

  // ── Progress state (no result yet) ───────────────────────────
  if (progress && (!result || result.status === "running")) {
    return (
      <DecompositionProgress
        stage={progress.stage}
        elapsed={progress.elapsed}
        onCancel={onCancel ?? onClose}
        error={progress.error}
      />
    );
  }

  if (!result) return null;

  // ── Error state ──────────────────────────────────────────────
  if (result.status === "error") {
    return (
      <div
        className="surface"
        style={{
          margin: "0",
          borderTop: "1px solid var(--color-border)",
          borderRadius: "0 0 0 10px",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            padding: "12px 16px",
          }}
        >
          <GitBranch size={14} style={{ color: "var(--color-red)" }} />
          <span className="type-section-header" style={{ color: "var(--color-red)" }}>
            Decomposition failed
          </span>
          <button
            onClick={onClose}
            style={{
              marginLeft: "auto",
              background: "none",
              border: "none",
              cursor: "pointer",
              color: "var(--color-text-tertiary)",
              padding: 4,
            }}
          >
            <X size={14} />
          </button>
        </div>
        <div
          className="type-body"
          style={{ padding: "0 16px 12px 42px", fontSize: 12 }}
        >
          {result.error}
        </div>
      </div>
    );
  }

  // ── Empty state ──────────────────────────────────────────────
  if (result.tasks.length === 0) {
    return (
      <div
        className="surface"
        style={{
          margin: "0",
          borderTop: "1px solid var(--color-border)",
          borderRadius: "0 0 0 10px",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            padding: "12px 16px",
          }}
        >
          <GitBranch size={14} style={{ color: "var(--color-amber)" }} />
          <span className="type-section-header">
            No tasks generated
          </span>
          <button
            onClick={onClose}
            style={{
              marginLeft: "auto",
              background: "none",
              border: "none",
              cursor: "pointer",
              color: "var(--color-text-tertiary)",
              padding: 4,
            }}
          >
            <X size={14} />
          </button>
        </div>
        <div
          className="type-body"
          style={{ padding: "0 16px 12px 42px", fontSize: 12 }}
        >
          The Architect returned an empty task list. Try refining the spec or
          using a different model.
        </div>
      </div>
    );
  }

  // ── Gate color ───────────────────────────────────────────────
  const gateColor = !result.gate
    ? null
    : result.gate.overall === "fail"
      ? "var(--color-red)"
      : result.gate.overall === "warn"
        ? "var(--color-amber)"
        : "var(--color-emerald)";

  const gateBg = !result.gate
    ? null
    : result.gate.overall === "fail"
      ? "rgba(239,68,100,0.08)"
      : result.gate.overall === "warn"
        ? "rgba(240,178,50,0.08)"
        : "rgba(68,204,119,0.08)";

  // ── Complete state ───────────────────────────────────────────
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        maxHeight: 480,
        overflow: "hidden",
        borderTop: "1px solid var(--color-border)",
        background: "var(--color-bg-card)",
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "10px 16px",
          borderBottom: "1px solid var(--color-border-light)",
          flexShrink: 0,
        }}
      >
        <GitBranch size={14} style={{ color: "var(--color-accent)" }} />
        <span className="type-section-header">Task Decomposition</span>

        {/* Stats row */}
        <div style={{ display: "flex", gap: 16, marginLeft: 4 }}>
          <Stat value={result.taskCount} label="tasks" />
          <Stat value={result.parallelChains} label="roots" />
          <Stat value={result.longestChain} label="depth" />
        </div>

        {/* Gate badge */}
        {result.gate && gateColor && gateBg && (
          <span
            className="type-badge"
            style={{
              color: gateColor,
              background: gateBg,
              padding: "2px 8px",
              borderRadius: 4,
            }}
          >
            Gate: {result.gate.overall}
          </span>
        )}

        {onGenerateChildRfcs && (
          <button
            onClick={onGenerateChildRfcs}
            disabled={generatingChildRfcs}
            style={{
              marginLeft: "auto",
              padding: "3px 10px", fontSize: 10, fontWeight: 600,
              color: generatingChildRfcs ? "var(--color-text-tertiary)" : "var(--color-bg)",
              background: generatingChildRfcs ? "var(--color-bg-elevated)" : "var(--color-accent)",
              border: "none", borderRadius: 4,
              cursor: generatingChildRfcs ? "default" : "pointer",
              transition: "all 150ms",
            }}
          >
            {generatingChildRfcs ? "Generating..." : "Generate Child RFCs"}
          </button>
        )}

        {onOpenBoard && (
          <button
            onClick={onOpenBoard}
            style={{
              marginLeft: onGenerateChildRfcs ? "0" : "auto",
              padding: "3px 10px", fontSize: 10, fontWeight: 500,
              color: "var(--color-accent)", background: "var(--color-accent-dim)",
              border: "1px solid var(--color-accent-glow)", borderRadius: 4,
              cursor: "pointer",
            }}
          >
            Open Plan →
          </button>
        )}

        <button
          onClick={onClose}
          style={{
            marginLeft: (onOpenBoard || onGenerateChildRfcs) ? "0" : "auto",
            background: "none",
            border: "none",
            cursor: "pointer",
            color: "var(--color-text-tertiary)",
            padding: 4,
          }}
        >
          <X size={14} />
        </button>
      </div>

      {/* Gate warnings */}
      {result.gate && <GateSummary gate={result.gate} />}

      {/* Phase groups */}
      <div
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "12px 16px",
          display: "flex",
          flexDirection: "column",
          gap: 16,
        }}
      >
        {phases.map((group) => (
          <div key={group.phase}>
            {/* Phase header */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                marginBottom: 8,
              }}
            >
              <Layers
                size={11}
                style={{ color: "var(--color-text-tertiary)" }}
              />
              <span className="type-compact-label">{group.label}</span>
              <span className="type-compact-label">
                {group.tasks.length > 1
                  ? `${group.tasks.length} parallel`
                  : ""}
              </span>
              <div
                style={{
                  flex: 1,
                  height: 1,
                  background: "var(--color-border-light)",
                }}
              />
            </div>

            {/* Task cards */}
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 8,
              }}
            >
              {group.tasks.map((task) => (
                <TaskCard
                  key={task.id}
                  task={task}
                  allTasks={result.tasks}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Small stat display ─────────────────────────────────────────

function Stat({ value, label }: { value: number; label: string }) {
  return (
    <span
      style={{
        display: "flex",
        alignItems: "baseline",
        gap: 3,
      }}
    >
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 13,
          fontWeight: 600,
          color: "var(--color-text)",
        }}
      >
        {value}
      </span>
      <span className="type-compact-label">{label}</span>
    </span>
  );
}
