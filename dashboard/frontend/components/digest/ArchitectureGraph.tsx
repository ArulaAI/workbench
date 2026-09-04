"use client";

import {
  ReactFlow,
  Background,
  Controls,
  Handle,
  Position,
  MarkerType,
  type Node,
  type Edge,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { DigestDomain, DigestRelationship, DigestLane } from "@/lib/graphql/queries/repository-digest";

export const LANE_ORDER: DigestLane[] = ["frontend", "api", "services", "data", "other"];

export const LANE_LABELS: Record<DigestLane, string> = {
  frontend: "Frontend",
  api: "API",
  services: "Services",
  data: "Data",
  other: "Other",
};

export const LANE_COLORS: Record<DigestLane, string> = {
  frontend: "var(--color-blue)",
  api: "var(--color-violet)",
  services: "var(--color-cyan)",
  data: "var(--color-amber)",
  other: "var(--color-text-tertiary)",
};

const NODE_W = 200;
const NODE_H = 58;
const ROW_SPACING = 88;
const LANE_SPACING = 260;
const LANE_TOP_MARGIN = 24;

type DomainNodeData = DigestDomain & { isSelected: boolean; [key: string]: unknown };

function DomainNodeComponent({ data }: NodeProps & { data: DomainNodeData }) {
  const color = LANE_COLORS[data.lane] ?? LANE_COLORS.other;
  return (
    <div
      className="surface"
      style={{
        width: NODE_W,
        padding: "8px 12px",
        borderLeft: `3px solid ${color}`,
        boxShadow: data.isSelected
          ? `0 0 0 2px ${color}, 0 1px 3px rgba(0,0,0,0.3)`
          : "0 1px 3px rgba(0,0,0,0.3)",
        cursor: "pointer",
      }}
      data-testid={`architecture-node-${data.id}`}
    >
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <div
        className="type-cell-label"
        style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
        title={data.label}
      >
        {data.label}
      </div>
      <div className="type-caption" style={{ marginTop: 2 }}>
        {data.fileCount} files · {data.symbolCount} symbols
      </div>
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
    </div>
  );
}

const nodeTypes = { domain: DomainNodeComponent };

/**
 * Pure, deterministic layout: no force simulation, no dagre. Domains are
 * sorted by id before grouping into lanes, and each lane's rows are
 * sorted by id too — the same digest always produces the same node
 * positions and the same edge draw order, regardless of GraphQL response
 * ordering.
 */
export function layoutArchitectureGraph(
  domains: DigestDomain[],
  relationships: DigestRelationship[],
  selectedId: string | null
): { nodes: Node<DomainNodeData>[]; edges: Edge[] } {
  const byLane = new Map<DigestLane, DigestDomain[]>();
  for (const lane of LANE_ORDER) byLane.set(lane, []);

  const sortedDomains = [...domains].sort((a, b) => a.id.localeCompare(b.id));
  for (const d of sortedDomains) {
    const bucket = byLane.get(d.lane) ?? byLane.get("other")!;
    bucket.push(d);
  }

  const nodes: Node<DomainNodeData>[] = [];
  LANE_ORDER.forEach((lane, laneIndex) => {
    const laneDomains = byLane.get(lane) ?? [];
    laneDomains.forEach((d, row) => {
      nodes.push({
        id: d.id,
        type: "domain",
        position: { x: laneIndex * LANE_SPACING, y: LANE_TOP_MARGIN + row * ROW_SPACING },
        data: { ...d, isSelected: d.id === selectedId },
        draggable: false,
        width: NODE_W,
        height: NODE_H,
      });
    });
  });

  const domainIds = new Set(domains.map((d) => d.id));
  const edges: Edge[] = [...relationships]
    .filter((r) => domainIds.has(r.source) && domainIds.has(r.target))
    .sort((a, b) => (a.source + "->" + a.target).localeCompare(b.source + "->" + b.target))
    .map((r) => ({
      id: `${r.source}->${r.target}`,
      source: r.source,
      target: r.target,
      type: "smoothstep",
      style: {
        stroke: "var(--color-text-tertiary)",
        strokeWidth: Math.min(1 + r.weight / 8, 5),
      },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: "var(--color-text-tertiary)",
        width: 14,
        height: 10,
      },
    }));

  return { nodes, edges };
}

export function ArchitectureGraph({
  domains,
  relationships,
  selectedId,
  onSelectDomain,
}: {
  domains: DigestDomain[];
  relationships: DigestRelationship[];
  selectedId: string | null;
  onSelectDomain: (id: string) => void;
}) {
  const { nodes, edges } = layoutArchitectureGraph(domains, relationships, selectedId);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodeClick={(_, node) => onSelectDomain(node.id)}
      fitView
      fitViewOptions={{ padding: 0.2 }}
      proOptions={{ hideAttribution: true }}
      minZoom={0.3}
      maxZoom={1.5}
      nodesConnectable={false}
      elementsSelectable
    >
      <Background color="var(--color-text-tertiary)" gap={24} size={1} />
      <Controls className="!bg-bg-elevated !border-border !shadow-none [&>button]:!bg-bg-card [&>button]:!border-border [&>button]:!text-text-secondary" />
    </ReactFlow>
  );
}
