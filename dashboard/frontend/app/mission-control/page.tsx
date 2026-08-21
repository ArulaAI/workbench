"use client";

import { useMemo } from "react";
import { useQuery, useSubscription } from "urql";
import {
  ReactFlow,
  Background,
  Controls,
  Panel,
  type Node,
  type Edge,
  Handle,
  Position,
  MarkerType,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import dagre from "@dagrejs/dagre";
import {
  MISSION_CONTROL_QUERY,
  TASK_STATUS_SUBSCRIPTION,
} from "@/lib/graphql/queries/mission-control";
import { FEATURES_QUERY } from "@/lib/graphql/queries/features";
import { useFeature } from "@/lib/hooks/use-feature-selector";
import { ProgressBar } from "@/components/shared/progress-bar";
import { CardSkeleton } from "@/components/shared/loading-skeleton";
import { statusColors } from "@/lib/utils/colors";
import { shortModel } from "@/lib/utils/model";

interface TaskData {
  [key: string]: unknown;
  id: string;
  title: string;
  status: string;
  agentModel: string | null;
  retryCount: number;
  dependsOn: string[];
  filesTouched: string[];
  error: string | null;
  acceptanceCriteria: string | null;
}

const NODE_W = 240;
const NODE_H = 64;

function TaskNodeComponent({ data }: { data: TaskData }) {
  const borderColor = statusColors[data.status] ?? statusColors.pending;
  const isRunning = data.status === "running";

  const modelLabel = data.agentModel ? shortModel(data.agentModel) : null;

  return (
    <div
      className="group relative rounded-lg bg-bg-card transition-shadow hover:shadow-lg"
      style={{
        width: NODE_W,
        borderLeft: `3px solid ${borderColor}`,
        boxShadow: isRunning
          ? `0 0 12px ${statusColors.running}, 0 1px 3px rgba(0,0,0,0.3)`
          : "0 1px 3px rgba(0,0,0,0.3)",
      }}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!h-1.5 !w-1.5 !border-0 !bg-text-tertiary"
      />

      <div className="px-3 py-2">
        {/* Meta line: #id · model · retry */}
        <div className="flex items-center gap-1 font-mono text-[10px] text-text-tertiary">
          <span>#{data.id}</span>
          {modelLabel && (
            <>
              <span className="opacity-40">·</span>
              <span>{modelLabel}</span>
            </>
          )}
          {data.retryCount > 0 && (
            <>
              <span className="opacity-40">·</span>
              <span className="text-red">retry {data.retryCount}</span>
            </>
          )}
        </div>

        {/* Title — primary element */}
        <div className="mt-0.5 line-clamp-2 text-[12px] font-medium leading-snug text-text">
          {data.title}
        </div>
      </div>

      <Handle
        type="source"
        position={Position.Bottom}
        className="!h-1.5 !w-1.5 !border-0 !bg-text-tertiary"
      />
    </div>
  );
}

const nodeTypes = { task: TaskNodeComponent };

function layoutGraph(tasks: TaskData[]): { nodes: Node[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "TB", ranksep: 120, nodesep: 60, marginx: 40, marginy: 40 });

  tasks.forEach((t) => {
    g.setNode(t.id, { width: NODE_W, height: NODE_H });
  });

  const edges: Edge[] = [];
  tasks.forEach((t) => {
    (t.dependsOn ?? []).forEach((dep) => {
      g.setEdge(dep, t.id);
      edges.push({
        id: `${dep}->${t.id}`,
        source: dep,
        target: t.id,
        type: "smoothstep",
        animated: t.status === "running",
        style: {
          stroke: "var(--color-text-tertiary)",
          strokeWidth: 1.5,
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: "var(--color-text-tertiary)",
          width: 16,
          height: 12,
        },
      });
    });
  });

  dagre.layout(g);

  const nodes: Node<TaskData>[] = tasks.map((t) => {
    const pos = g.node(t.id);
    return {
      id: t.id,
      type: "task",
      position: { x: pos.x - NODE_W / 2, y: pos.y - NODE_H / 2 },
      data: t,
    };
  });

  return { nodes, edges };
}

export default function MissionControlPage() {
  const { selectedFeature } = useFeature();
  const [{ data: featData }] = useQuery({ query: FEATURES_QUERY });
  const feature =
    selectedFeature ?? featData?.features?.[0]?.name ?? "speed-security";

  const [{ data, fetching, error }] = useQuery({
    query: MISSION_CONTROL_QUERY,
    variables: { feature },
    pause: !feature,
  });

  // Live task status updates via WebSocket
  const [{ data: subData }] = useSubscription({
    query: TASK_STATUS_SUBSCRIPTION,
    variables: { feature },
    pause: !feature,
  });

  // Merge subscription updates into query data
  const liveTasks: TaskData[] | null = useMemo(() => {
    const tasks = data?.missionControl?.tasks;
    if (!tasks) return null;
    if (!subData?.taskStatusChanged) return tasks;
    const { taskId, status } = subData.taskStatusChanged;
    return tasks.map((t: TaskData) =>
      t.id === taskId ? { ...t, status } : t
    );
  }, [data, subData]);

  // Recompute status counts from live tasks so they stay in sync
  const sc = useMemo(() => {
    const tasks = liveTasks ?? data?.missionControl?.tasks;
    if (!tasks) return { pending: 0, running: 0, done: 0, failed: 0, reviewing: 0 };
    const counts = { pending: 0, running: 0, done: 0, failed: 0, reviewing: 0 };
    for (const t of tasks) {
      const s = t.status as keyof typeof counts;
      if (s in counts) counts[s]++;
    }
    return counts;
  }, [liveTasks, data]);

  if (fetching) {
    return (
      <div className="grid gap-4 md:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <CardSkeleton key={i} />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="surface p-4 text-red">
        Error loading mission control: {error.message}
      </div>
    );
  }

  const mc = data?.missionControl;
  if (!mc) {
    return (
      <div className="text-text-secondary">
        No data for feature &quot;{feature}&quot;. Run{" "}
        <code className="rounded bg-bg-card px-1.5 py-0.5 text-accent">
          speed plan
        </code>{" "}
        first.
      </div>
    );
  }

  const tasks = liveTasks ?? mc.tasks;
  const total = mc.taskCount;

  const { nodes, edges } = layoutGraph(tasks);

  const statusLegend = [
    { label: "Done", color: "var(--color-emerald)" },
    { label: "Running", color: "var(--color-amber)" },
    { label: "Failed", color: "var(--color-red)" },
    { label: "Review", color: "var(--color-blue)" },
    { label: "Pending", color: "var(--color-text-tertiary)" },
  ];

  return (
    <div className="flex h-full flex-col gap-4">
      {/* Progress summary */}
      <div className="surface flex items-center justify-between px-4 py-3">
        <div className="flex items-center gap-4">
          <span className="type-section-header">{feature}</span>
          <span className="font-mono text-[12px] text-text-secondary">
            {sc.done}/{total} complete
          </span>
        </div>
        <div className="flex-1 mx-6 max-w-md">
          <ProgressBar
            total={total}
            segments={[
              { value: sc.done, color: "var(--color-emerald)", label: "Done" },
              { value: sc.running, color: "var(--color-amber)", label: "Running" },
              { value: sc.failed, color: "var(--color-red)", label: "Failed" },
              { value: sc.reviewing, color: "var(--color-blue)", label: "Reviewing" },
              { value: sc.pending, color: "var(--color-text-tertiary)", label: "Pending" },
            ]}
            height={4}
          />
        </div>
      </div>

      {/* Task DAG */}
      <div className="surface flex-1" style={{ minHeight: 500 }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.15 }}
          proOptions={{ hideAttribution: true }}
          minZoom={0.3}
          maxZoom={1.5}
        >
          <Background color="var(--color-text-tertiary)" gap={24} size={1} />
          <Controls
            className="!bg-bg-elevated !border-border !shadow-none [&>button]:!bg-bg-card [&>button]:!border-border [&>button]:!text-text-secondary"
          />

          {/* Legend — bottom-right panel */}
          <Panel position="bottom-right">
            <div className="flex items-center gap-4 rounded-lg border border-border bg-bg-elevated/90 px-3 py-2 backdrop-blur-sm">
              {statusLegend.map((s) => (
                <div key={s.label} className="flex items-center gap-1.5">
                  <div
                    className="h-2 w-2 rounded-full"
                    style={{ backgroundColor: s.color }}
                  />
                  <span className="font-mono text-[10px] text-text-tertiary">
                    {s.label}
                  </span>
                </div>
              ))}
              <div className="ml-1 flex items-center gap-1.5 border-l border-border pl-3">
                <svg width="20" height="8" className="text-text-tertiary">
                  <line x1="0" y1="4" x2="14" y2="4" stroke="currentColor" strokeWidth="1.5" />
                  <polygon points="14,1 20,4 14,7" fill="currentColor" />
                </svg>
                <span className="font-mono text-[10px] text-text-tertiary">
                  depends on
                </span>
              </div>
            </div>
          </Panel>
        </ReactFlow>
      </div>
    </div>
  );
}
