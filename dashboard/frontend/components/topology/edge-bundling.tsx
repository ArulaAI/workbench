"use client";

import { useMemo, useState, useCallback, useRef } from "react";
import {
  hierarchy,
  cluster as d3Cluster,
  type HierarchyPointNode,
} from "d3-hierarchy";
import { lineRadial, curveBundle } from "d3-shape";

/* ── Types ─────────────────────────────────────────────────────── */

interface NodeData {
  id: string;
  name: string;
  kind: string;
  file: string;
  line: number;
  cluster: string;
  impact: {
    blastRadius: number;
    centrality: number;
    dependents: number;
    stability: number;
  };
}

interface EdgeData {
  source: string;
  target: string;
  type: string;
}

interface ClusterData {
  id: string;
  symbolCount: number;
  files: string[];
  kinds: string[];
  avgBlastRadius: number;
}

interface TreeDatum {
  name: string;
  children?: TreeDatum[];
  nodeData?: NodeData;
}

interface Props {
  nodes: NodeData[];
  edges: EdgeData[];
  clusters: ClusterData[];
}

/* ── Constants ─────────────────────────────────────────────────── */

const SIZE = 960;
const HALF = SIZE / 2;
const RADIUS = 390;
const INNER_RADIUS = 350;

// Fixed directory → color mapping (meaningful, not random)
const DIR_COLORS: Record<string, string> = {
  lib: "#00d4aa",       // teal — core library
  tests: "#8b5cf6",     // violet — test suite
  providers: "#4ba6ee", // blue — providers
  speed: "#f0b232",     // amber — entrypoint
  scripts: "#44cc77",   // emerald — scripts
  example: "#ff6699",   // rose — examples
  other: "#9494a3",     // grey fallback
};

/* ── Helpers ───────────────────────────────────────────────────── */

function polar(angle: number, r: number) {
  return { x: r * Math.sin(angle), y: -r * Math.cos(angle) };
}

function topDir(filePath: string): string {
  const first = filePath.split("/")[0];
  return DIR_COLORS[first] ? first : "other";
}

function svgArc(startAngle: number, endAngle: number, r: number): string {
  const s = polar(startAngle, r);
  const e = polar(endAngle, r);
  const large = endAngle - startAngle > Math.PI ? 1 : 0;
  return `M ${s.x} ${s.y} A ${r} ${r} 0 ${large} 1 ${e.x} ${e.y}`;
}

/* ── Component ─────────────────────────────────────────────────── */

export function EdgeBundling({ nodes, edges, clusters }: Props) {
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);
  const [tooltip, setTooltip] = useState<{
    x: number;
    y: number;
    node: NodeData;
  } | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const {
    leafMap,
    edgePaths,
    dirSegments,
    adjacencyMap,
    neighborMap,
    dirStats,
  } = useMemo(() => {
    // Group nodes by cluster
    const byCluster = new Map<string, NodeData[]>();
    for (const n of nodes) {
      const list = byCluster.get(n.cluster) || [];
      list.push(n);
      byCluster.set(n.cluster, list);
    }

    // Determine directory for each cluster (from first file)
    const clusterDir = new Map<string, string>();
    for (const c of clusters) {
      const dir = c.files.length > 0 ? topDir(c.files[0]) : "other";
      clusterDir.set(c.id, dir);
    }

    // Group clusters by directory, sort within each
    const dirClusters = new Map<string, ClusterData[]>();
    for (const c of clusters) {
      if ((byCluster.get(c.id)?.length ?? 0) === 0) continue;
      const dir = clusterDir.get(c.id) || "other";
      const list = dirClusters.get(dir) || [];
      list.push(c);
      dirClusters.set(dir, list);
    }

    // Sort directories by size (largest first) for visual prominence
    const sortedDirs = [...dirClusters.entries()]
      .sort((a, b) => {
        const countA = a[1].reduce((s, c) => s + (byCluster.get(c.id)?.length ?? 0), 0);
        const countB = b[1].reduce((s, c) => s + (byCluster.get(c.id)?.length ?? 0), 0);
        return countB - countA;
      });

    // Sort clusters within each directory by file path
    for (const [, cls] of sortedDirs) {
      cls.sort((a, b) => (a.files[0] || "").localeCompare(b.files[0] || ""));
    }

    // Build hierarchy: root → directory → cluster → symbol
    const tree: TreeDatum = {
      name: "root",
      children: sortedDirs.map(([dir, cls]) => ({
        name: dir,
        children: cls.map((c) => ({
          name: c.id,
          children: (byCluster.get(c.id) || []).map((n) => ({
            name: n.id,
            nodeData: n,
          })),
        })),
      })),
    };

    // Radial layout
    const root = hierarchy(tree);
    d3Cluster<TreeDatum>()
      .size([2 * Math.PI, INNER_RADIUS])
      .separation((a, b) => (a.parent === b.parent ? 1 : 2) / a.depth)(root);

    // Leaf lookup
    const lMap = new Map<string, HierarchyPointNode<TreeDatum>>();
    for (const leaf of root.leaves()) {
      lMap.set(leaf.data.name, leaf as HierarchyPointNode<TreeDatum>);
    }

    // Edge bundling
    const line = lineRadial<HierarchyPointNode<TreeDatum>>()
      .curve(curveBundle.beta(0.85))
      .angle((d) => d.x)
      .radius((d) => d.y);

    const paths: Array<{ path: string; source: string; target: string }> = [];
    for (const edge of edges) {
      const src = lMap.get(edge.source);
      const tgt = lMap.get(edge.target);
      if (!src || !tgt) continue;
      const p = line(src.path(tgt) as HierarchyPointNode<TreeDatum>[]);
      if (p) paths.push({ path: p, source: edge.source, target: edge.target });
    }

    // Directory arc segments (from the directory-level children of root)
    const segments: Array<{
      dir: string;
      color: string;
      startAngle: number;
      endAngle: number;
      midAngle: number;
      nodeCount: number;
    }> = [];

    for (const dirChild of (root.children || [])) {
      const leaves = dirChild.leaves() as HierarchyPointNode<TreeDatum>[];
      if (leaves.length === 0) continue;
      const angles = leaves.map((l) => l.x);
      const min = Math.min(...angles);
      const max = Math.max(...angles);
      const pad = 0.008;
      segments.push({
        dir: dirChild.data.name,
        color: DIR_COLORS[dirChild.data.name] || DIR_COLORS.other,
        startAngle: min - pad,
        endAngle: max + pad,
        midAngle: (min + max) / 2,
        nodeCount: leaves.length,
      });
    }

    // Stats per directory
    const stats = new Map<string, number>();
    for (const seg of segments) stats.set(seg.dir, seg.nodeCount);

    // Adjacency maps
    const adjMap = new Map<string, Set<number>>();
    paths.forEach((e, i) => {
      if (!adjMap.has(e.source)) adjMap.set(e.source, new Set());
      if (!adjMap.has(e.target)) adjMap.set(e.target, new Set());
      adjMap.get(e.source)!.add(i);
      adjMap.get(e.target)!.add(i);
    });

    const nbMap = new Map<string, Set<string>>();
    for (const edge of edges) {
      if (!nbMap.has(edge.source)) nbMap.set(edge.source, new Set());
      if (!nbMap.has(edge.target)) nbMap.set(edge.target, new Set());
      nbMap.get(edge.source)!.add(edge.target);
      nbMap.get(edge.target)!.add(edge.source);
    }

    return {
      leafMap: lMap,
      edgePaths: paths,
      dirSegments: segments,
      adjacencyMap: adjMap,
      neighborMap: nbMap,
      dirStats: stats,
    };
  }, [nodes, edges, clusters]);

  /* Hover-derived sets */
  const connectedEdges = hoveredNode
    ? adjacencyMap.get(hoveredNode) ?? new Set<number>()
    : null;
  const connectedNodes = hoveredNode
    ? neighborMap.get(hoveredNode) ?? new Set<string>()
    : null;

  /* Event handlers */
  const onDotEnter = useCallback(
    (nodeId: string, e: React.MouseEvent) => {
      setHoveredNode(nodeId);
      const leaf = leafMap.get(nodeId);
      if (!leaf?.data.nodeData || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      setTooltip({
        x: e.clientX - rect.left,
        y: e.clientY - rect.top,
        node: leaf.data.nodeData,
      });
    },
    [leafMap]
  );

  const onDotLeave = useCallback(() => {
    setHoveredNode(null);
    setTooltip(null);
  }, []);

  return (
    <div ref={containerRef} className="relative h-full w-full">
      <svg
        viewBox={`${-HALF} ${-HALF} ${SIZE} ${SIZE}`}
        className="h-full w-full"
        preserveAspectRatio="xMidYMid meet"
      >
        {/* Ambient center glow */}
        <defs>
          <radialGradient id="center-glow">
            <stop offset="0%" stopColor="#00d4aa" stopOpacity="0.03" />
            <stop offset="50%" stopColor="#8b5cf6" stopOpacity="0.015" />
            <stop offset="100%" stopColor="transparent" stopOpacity="0" />
          </radialGradient>
        </defs>
        <circle r={INNER_RADIUS * 0.5} fill="url(#center-glow)" />

        {/* Edge bundles */}
        <g>
          {edgePaths.map((e, i) => {
            const active = connectedEdges?.has(i);
            const outgoing = e.source === hoveredNode;
            return (
              <path
                key={i}
                d={e.path}
                fill="none"
                stroke={
                  active
                    ? outgoing
                      ? "var(--color-accent)"
                      : "var(--color-violet)"
                    : "rgba(255,255,255,0.15)"
                }
                strokeWidth={active ? 1.8 : 0.6}
                opacity={connectedEdges ? (active ? 0.8 : 0.03) : 0.12}
                style={{ transition: "opacity 0.2s ease" }}
              />
            );
          })}
        </g>

        {/* Directory arc segments */}
        <g>
          {dirSegments.map((seg) => (
            <path
              key={seg.dir}
              d={svgArc(seg.startAngle, seg.endAngle, RADIUS)}
              fill="none"
              stroke={seg.color}
              strokeWidth={6}
              opacity={0.7}
              strokeLinecap="round"
            />
          ))}
        </g>

        {/* Directory labels on the ring */}
        <g>
          {dirSegments.map((seg) => {
            const labelR = RADIUS + 20;
            const pos = polar(seg.midAngle, labelR);
            const angleDeg = (seg.midAngle * 180) / Math.PI;
            const flip = angleDeg > 90 && angleDeg < 270;
            return (
              <g key={`label-${seg.dir}`}>
                <text
                  x={pos.x}
                  y={pos.y}
                  textAnchor={flip ? "end" : "start"}
                  dominantBaseline="central"
                  transform={`rotate(${angleDeg - 90}, ${pos.x}, ${pos.y})`}
                  className="pointer-events-none"
                  style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: "11px",
                    fontWeight: 600,
                    fill: seg.color,
                  }}
                >
                  {seg.dir}/
                </text>
                <text
                  x={pos.x}
                  y={pos.y + (flip ? -14 : 14)}
                  textAnchor={flip ? "end" : "start"}
                  dominantBaseline="central"
                  transform={`rotate(${angleDeg - 90}, ${pos.x}, ${pos.y + (flip ? -14 : 14)})`}
                  className="pointer-events-none"
                  style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: "9px",
                    fontWeight: 400,
                    fill: "var(--color-text-tertiary)",
                  }}
                >
                  {seg.nodeCount} symbols
                </text>
              </g>
            );
          })}
        </g>

        {/* Symbol dots */}
        <g>
          {Array.from(leafMap.entries()).map(([id, leaf]) => {
            const pos = polar(leaf.x, leaf.y);
            const nd = leaf.data.nodeData;
            const dir = nd ? topDir(nd.file) : "other";
            const color = DIR_COLORS[dir] || DIR_COLORS.other;
            const isHovered = hoveredNode === id;
            const isConnected = connectedNodes?.has(id);
            const dim = connectedEdges && !isConnected && !isHovered;

            return (
              <circle
                key={id}
                cx={pos.x}
                cy={pos.y}
                r={isHovered ? 5 : isConnected ? 3.5 : 2}
                fill={color}
                opacity={dim ? 0.08 : isHovered ? 1 : isConnected ? 1 : 0.5}
                className="cursor-pointer"
                style={{ transition: "opacity 0.15s ease" }}
                onMouseEnter={(e) => onDotEnter(id, e)}
                onMouseLeave={onDotLeave}
              />
            );
          })}
        </g>

        {/* Hovered node label */}
        {hoveredNode &&
          leafMap.has(hoveredNode) &&
          (() => {
            const leaf = leafMap.get(hoveredNode)!;
            const pos = polar(leaf.x, RADIUS + 36);
            const angleDeg = (leaf.x * 180) / Math.PI;
            const flip = angleDeg > 90 && angleDeg < 270;
            return (
              <text
                x={pos.x}
                y={pos.y}
                textAnchor={flip ? "end" : "start"}
                dominantBaseline="central"
                transform={`rotate(${angleDeg - 90}, ${pos.x}, ${pos.y})`}
                className="pointer-events-none fill-text"
                style={{ fontFamily: "var(--font-mono)", fontSize: "10px", fontWeight: 500 }}
              >
                {leaf.data.nodeData?.name || leaf.data.name}
              </text>
            );
          })()}
      </svg>

      {/* Legend panel — bottom right */}
      <div className="absolute bottom-4 right-4 rounded-lg border border-border bg-bg-elevated/90 px-4 py-3 backdrop-blur-sm">
        <div
          className="mb-2 text-[10px] font-medium uppercase tracking-wider text-text-tertiary"
          style={{ fontFamily: "var(--font-mono)" }}
        >
          Directories
        </div>
        <div className="space-y-1.5">
          {dirSegments.map((seg) => (
            <div key={seg.dir} className="flex items-center gap-2.5">
              <div
                className="h-2 w-4 rounded-sm"
                style={{ backgroundColor: seg.color, opacity: 0.8 }}
              />
              <span
                className="text-[11px] text-text-secondary"
                style={{ fontFamily: "var(--font-mono)" }}
              >
                {seg.dir}/
              </span>
              <span className="text-[10px] text-text-tertiary">
                {seg.nodeCount}
              </span>
            </div>
          ))}
        </div>
        <div className="mt-3 border-t border-border pt-2">
          <div className="flex items-center gap-2.5">
            <div className="h-0.5 w-4 rounded-full bg-accent" />
            <span className="text-[10px] text-text-tertiary">outgoing dep</span>
          </div>
          <div className="mt-1 flex items-center gap-2.5">
            <div className="h-0.5 w-4 rounded-full bg-violet" />
            <span className="text-[10px] text-text-tertiary">incoming dep</span>
          </div>
        </div>
      </div>

      {/* Tooltip */}
      {tooltip && (
        <div
          className="pointer-events-none absolute z-10 rounded-lg border border-border bg-bg-elevated/95 px-3 py-2 shadow-lg backdrop-blur-sm"
          style={{ left: tooltip.x + 16, top: tooltip.y - 12 }}
        >
          <div
            className="text-[12px] font-medium text-text"
            style={{ fontFamily: "var(--font-mono)" }}
          >
            {tooltip.node.name}
          </div>
          <div className="mt-0.5 text-[11px] text-text-secondary">
            {tooltip.node.file}:{tooltip.node.line}
          </div>
          <div className="mt-1 flex items-center gap-3 text-[10px] text-text-tertiary">
            <span>{tooltip.node.kind}</span>
            <span>blast {tooltip.node.impact.blastRadius}</span>
            <span>{tooltip.node.impact.dependents} deps</span>
          </div>
        </div>
      )}
    </div>
  );
}
