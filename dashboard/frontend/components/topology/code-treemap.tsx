"use client";

import { useMemo, useState, useRef, useEffect } from "react";
import {
  hierarchy,
  treemap,
  treemapSquarify,
  type HierarchyRectangularNode,
} from "d3-hierarchy";

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

interface ClusterData {
  id: string;
  symbolCount: number;
  files: string[];
  kinds: string[];
  avgBlastRadius: number;
}

interface SymbolSummary {
  name: string;
  kind: string;
  blast: number;
  dependents: number;
}

interface FileDatum {
  name: string;
  displayName: string;
  dir: string;
  symbolCount: number;
  maxBlast: number;
  totalDependents: number;
  kinds: Map<string, number>; // kind → count
  topSymbols: SymbolSummary[]; // top 5 by blast radius
  isAggregate?: boolean;
  aggregateCount?: number;
  value?: number;
  children?: FileDatum[];
}

interface Props {
  nodes: NodeData[];
  clusters: ClusterData[];
}

/* ── Color system ──────────────────────────────────────────────── */

// Each directory gets a hue+saturation. Blast radius drives lightness.
const DIR_HSL: Record<string, { h: number; s: number; accent: string }> = {
  lib:       { h: 165, s: 70, accent: "#00d4aa" },
  tests:     { h: 260, s: 50, accent: "#8b5cf6" },
  providers: { h: 210, s: 65, accent: "#4ba6ee" },
  speed:     { h: 42,  s: 75, accent: "#f0b232" },
  scripts:   { h: 145, s: 55, accent: "#44cc77" },
  example:   { h: 340, s: 60, accent: "#ff6699" },
  other:     { h: 240, s: 10, accent: "#9494a3" },
};

function cellColor(dir: string, blastNorm: number): string {
  const { h, s } = DIR_HSL[dir] || DIR_HSL.other;
  const l = 16 + blastNorm * 24; // 16% → 40% lightness
  return `hsl(${h}, ${s}%, ${l}%)`;
}

function cellBorder(dir: string, blastNorm: number): string {
  const { h, s } = DIR_HSL[dir] || DIR_HSL.other;
  const l = 24 + blastNorm * 20;
  return `hsl(${h}, ${s}%, ${l}%)`;
}

function accent(dir: string): string {
  return (DIR_HSL[dir] || DIR_HSL.other).accent;
}

function topDir(filePath: string): string {
  const first = filePath.split("/")[0];
  return DIR_HSL[first] ? first : "other";
}

function fileName(filePath: string): string {
  return filePath.split("/").pop() || filePath;
}

/* ── Component ─────────────────────────────────────────────────── */

export function CodeTreemap({ nodes, clusters }: Props) {
  const [hoveredFile, setHoveredFile] = useState<string | null>(null);
  const [tooltip, setTooltip] = useState<{
    x: number;
    y: number;
    data: FileDatum;
  } | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dims, setDims] = useState({ width: 1200, height: 700 });

  // Track container size for correct aspect ratio
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const obs = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        if (width > 0 && height > 0) setDims({ width, height });
      }
    });
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  const { leaves, dirs, dirLegend, globalMaxBlast } = useMemo(() => {
    // Group nodes by file with full symbol data
    const byFile = new Map<
      string,
      { symbols: NodeData[] }
    >();
    for (const n of nodes) {
      const entry = byFile.get(n.file) || { symbols: [] };
      entry.symbols.push(n);
      byFile.set(n.file, entry);
    }

    function buildFileDatum(file: string, syms: NodeData[]): FileDatum {
      const kindCounts = new Map<string, number>();
      let maxBlast = 0;
      let totalDeps = 0;
      for (const s of syms) {
        kindCounts.set(s.kind, (kindCounts.get(s.kind) || 0) + 1);
        maxBlast = Math.max(maxBlast, s.impact.blastRadius);
        totalDeps += s.impact.dependents;
      }
      const topSymbols = [...syms]
        .sort((a, b) => b.impact.blastRadius - a.impact.blastRadius)
        .slice(0, 5)
        .map((s) => ({
          name: s.name,
          kind: s.kind,
          blast: s.impact.blastRadius,
          dependents: s.impact.dependents,
        }));

      return {
        name: file,
        displayName: fileName(file),
        dir: topDir(file),
        symbolCount: syms.length,
        maxBlast,
        totalDependents: totalDeps,
        kinds: kindCounts,
        topSymbols,
        value: syms.length,
      };
    }

    // Group by directory, aggregate small files
    const MIN_SYM = 4;
    const dirMap = new Map<string, FileDatum[]>();
    for (const [file, { symbols }] of byFile) {
      const dir = topDir(file);
      const list = dirMap.get(dir) || [];
      list.push(buildFileDatum(file, symbols));
      dirMap.set(dir, list);
    }

    const tree: FileDatum = {
      name: "root",
      displayName: "Codebase",
      dir: "",
      symbolCount: nodes.length,
      maxBlast: 0,
      totalDependents: 0,
      kinds: new Map(),
      topSymbols: [],
      children: [...dirMap.entries()]
        .sort(
          (a, b) =>
            b[1].reduce((s, f) => s + f.symbolCount, 0) -
            a[1].reduce((s, f) => s + f.symbolCount, 0)
        )
        .map(([dir, files]) => {
          const big = files.filter((f) => f.symbolCount >= MIN_SYM);
          const small = files.filter((f) => f.symbolCount < MIN_SYM);
          const children = big.sort((a, b) => b.symbolCount - a.symbolCount);

          if (small.length > 0) {
            const mergedKinds = new Map<string, number>();
            let totalDeps = 0;
            for (const f of small) {
              for (const [k, v] of f.kinds) mergedKinds.set(k, (mergedKinds.get(k) || 0) + v);
              totalDeps += f.totalDependents;
            }
            children.push({
              name: `${dir}/__small__`,
              displayName: `${small.length} small files`,
              dir,
              symbolCount: small.reduce((s, f) => s + f.symbolCount, 0),
              maxBlast: Math.max(...small.map((f) => f.maxBlast)),
              totalDependents: totalDeps,
              kinds: mergedKinds,
              topSymbols: [],
              value: small.reduce((s, f) => s + f.symbolCount, 0),
              isAggregate: true,
              aggregateCount: small.length,
            });
          }

          return {
            name: dir,
            displayName: `${dir}/`,
            dir,
            symbolCount: files.reduce((s, f) => s + f.symbolCount, 0),
            maxBlast: Math.max(...files.map((f) => f.maxBlast), 0),
            totalDependents: 0,
            kinds: new Map<string, number>(),
            topSymbols: [],
            children,
          };
        }),
    };

    // Layout at actual container dimensions
    const root = hierarchy(tree)
      .sum((d) => d.value ?? 0)
      .sort((a, b) => (b.value ?? 0) - (a.value ?? 0));

    treemap<FileDatum>()
      .size([dims.width, dims.height])
      .paddingInner(3)
      .paddingTop(32)
      .paddingOuter(8)
      .tile(treemapSquarify.ratio(1.618))(root);

    type RNode = HierarchyRectangularNode<FileDatum>;
    const leafRects: RNode[] = [];
    const dirRects: RNode[] = [];

    for (const node of root.descendants() as RNode[]) {
      if (node.depth === 1) dirRects.push(node);
      if (!node.children) leafRects.push(node);
    }

    const maxB = Math.max(...leafRects.map((l) => l.data.maxBlast), 1);

    return {
      leaves: leafRects,
      dirs: dirRects,
      dirLegend: dirRects.map((d) => ({
        dir: d.data.name,
        accent: accent(d.data.name),
        count: d.value ?? 0,
      })),
      globalMaxBlast: maxB,
    };
  }, [nodes, clusters, dims]);

  const handleMouseEnter = (
    file: string,
    data: FileDatum,
    e: React.MouseEvent
  ) => {
    setHoveredFile(file);
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    setTooltip({ x: e.clientX - rect.left, y: e.clientY - rect.top, data });
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!tooltip || !containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    setTooltip((prev) =>
      prev ? { ...prev, x: e.clientX - rect.left, y: e.clientY - rect.top } : null
    );
  };

  const handleMouseLeave = () => {
    setHoveredFile(null);
    setTooltip(null);
  };

  return (
    <div ref={containerRef} className="relative h-full w-full overflow-hidden">
      {/* Directory groups */}
      {dirs.map((d) => {
        const a = accent(d.data.name);
        const w = d.x1 - d.x0;
        const h = d.y1 - d.y0;
        if (w < 1 || h < 1) return null;
        return (
          <div
            key={`dir-${d.data.name}`}
            className="absolute"
            style={{
              left: d.x0,
              top: d.y0,
              width: w,
              height: h,
              borderRadius: 12,
              background: `${a}06`,
              border: `1px solid ${a}18`,
            }}
          >
            <div className="absolute left-3 top-2 z-10 flex items-baseline gap-2.5">
              <span
                className="text-[13px] font-bold tracking-wide"
                style={{ fontFamily: "var(--font-mono)", color: a }}
              >
                {d.data.displayName}
              </span>
              <span className="text-[11px]" style={{ color: `${a}70` }}>
                {d.value} symbols
              </span>
            </div>
          </div>
        );
      })}

      {/* File cells */}
      {leaves.map((d) => {
        const dir = d.data.dir || "other";
        const blastNorm = d.data.maxBlast / globalMaxBlast;
        const isHovered = hoveredFile === d.data.name;
        const w = d.x1 - d.x0;
        const h = d.y1 - d.y0;
        if (w < 2 || h < 2) return null;

        const bg = cellColor(dir, blastNorm);
        const border = cellBorder(dir, blastNorm);

        // Label sizing based on cell area
        const area = w * h;
        const showName = area > 3500 && w > 60;
        const showSmallName = !showName && area > 1200 && w > 50;

        return (
          <div
            key={d.data.name}
            className="absolute cursor-pointer overflow-hidden"
            style={{
              left: d.x0,
              top: d.y0,
              width: w,
              height: h,
              borderRadius: 8,
              background: bg,
              border: `1px solid ${isHovered ? accent(dir) : border}`,
              boxShadow: isHovered
                ? `0 0 16px ${accent(dir)}40, inset 0 1px 0 rgba(255,255,255,0.06)`
                : "inset 0 1px 0 rgba(255,255,255,0.04)",
              transform: isHovered ? "scale(1.01)" : "scale(1)",
              transition: "transform 0.1s ease, border-color 0.1s ease, box-shadow 0.1s ease",
              zIndex: isHovered ? 10 : 1,
            }}
            onMouseEnter={(e) => handleMouseEnter(d.data.name, d.data, e)}
            onMouseMove={handleMouseMove}
            onMouseLeave={handleMouseLeave}
          >
            {showName && (
              <div className="flex h-full flex-col justify-end p-2">
                <div
                  className="truncate text-[11px] font-semibold leading-tight"
                  style={{
                    fontFamily: "var(--font-mono)",
                    color: "rgba(255,255,255,0.88)",
                  }}
                >
                  {d.data.displayName}
                </div>
                <div
                  className="mt-0.5 text-[10px]"
                  style={{ color: "rgba(255,255,255,0.4)" }}
                >
                  {d.data.symbolCount} symbols
                </div>
              </div>
            )}
            {showSmallName && (
              <div className="flex h-full items-end p-1.5">
                <div
                  className="truncate text-[9px] font-medium"
                  style={{
                    fontFamily: "var(--font-mono)",
                    color: "rgba(255,255,255,0.55)",
                  }}
                >
                  {d.data.displayName}
                </div>
              </div>
            )}
          </div>
        );
      })}

      {/* Legend */}
      <div className="absolute bottom-4 right-4 z-20 rounded-xl border border-border bg-bg-elevated/90 px-4 py-3.5 backdrop-blur-sm">
        <div
          className="mb-2.5 text-[10px] font-medium uppercase tracking-wider text-text-tertiary"
          style={{ fontFamily: "var(--font-mono)" }}
        >
          Directories
        </div>
        <div className="space-y-2">
          {dirLegend.map((d) => (
            <div key={d.dir} className="flex items-center gap-3">
              <div
                className="h-3 w-5 rounded"
                style={{ backgroundColor: d.accent, opacity: 0.6 }}
              />
              <span
                className="text-[11px] text-text-secondary"
                style={{ fontFamily: "var(--font-mono)" }}
              >
                {d.dir}/
              </span>
              <span className="ml-auto tabular-nums text-[10px] text-text-tertiary">
                {d.count}
              </span>
            </div>
          ))}
        </div>
        <div className="mt-3 space-y-1 border-t border-border pt-2.5">
          <div className="flex items-center gap-2 text-[10px] text-text-tertiary">
            <span className="inline-block h-3 w-6 rounded" style={{ background: "linear-gradient(90deg, hsl(165,70%,16%), hsl(165,70%,40%))" }} />
            blast radius (dark → bright)
          </div>
          <div className="text-[10px] text-text-tertiary">
            Rectangle size = symbol count
          </div>
        </div>
      </div>

      {/* Tooltip */}
      {tooltip && (
        <div
          className="pointer-events-none absolute z-30 min-w-[220px] max-w-[320px] rounded-xl border border-border bg-bg-elevated/95 shadow-xl backdrop-blur-sm"
          style={{
            left: Math.min(tooltip.x + 16, dims.width - 340),
            top: Math.max(tooltip.y - 12, 8),
          }}
        >
          {/* Header */}
          <div className="border-b border-border px-4 py-2.5">
            <div
              className="text-[12px] font-semibold text-text"
              style={{ fontFamily: "var(--font-mono)" }}
            >
              {tooltip.data.isAggregate
                ? `${tooltip.data.aggregateCount} small files`
                : tooltip.data.name}
            </div>
            {/* Kind breakdown: "14 functions · 2 classes" */}
            <div className="mt-1 text-[10px] text-text-tertiary">
              {[...tooltip.data.kinds.entries()]
                .sort((a, b) => b[1] - a[1])
                .map(([kind, count]) => `${count} ${kind}${count > 1 ? "s" : ""}`)
                .join(" · ")}
            </div>
          </div>

          {/* Stats */}
          <div className="flex gap-4 border-b border-border px-4 py-2">
            <div>
              <div className="text-[10px] text-text-tertiary">Symbols</div>
              <div className="text-[13px] font-semibold text-text" style={{ fontFamily: "var(--font-mono)" }}>
                {tooltip.data.symbolCount}
              </div>
            </div>
            <div>
              <div className="text-[10px] text-text-tertiary">Max Blast</div>
              <div className="text-[13px] font-semibold text-text" style={{ fontFamily: "var(--font-mono)" }}>
                {tooltip.data.maxBlast}
              </div>
            </div>
            <div>
              <div className="text-[10px] text-text-tertiary">Dependents</div>
              <div className="text-[13px] font-semibold text-text" style={{ fontFamily: "var(--font-mono)" }}>
                {tooltip.data.totalDependents}
              </div>
            </div>
          </div>

          {/* Top symbols by blast radius */}
          {tooltip.data.topSymbols.length > 0 && (
            <div className="px-4 py-2.5">
              <div className="mb-1.5 text-[9px] font-medium uppercase tracking-wider text-text-tertiary">
                Highest blast radius
              </div>
              <div className="space-y-1">
                {tooltip.data.topSymbols.map((sym, i) => (
                  <div
                    key={i}
                    className="flex items-center justify-between gap-3"
                  >
                    <span
                      className="truncate text-[11px] text-text-secondary"
                      style={{ fontFamily: "var(--font-mono)" }}
                    >
                      {sym.name}
                    </span>
                    <span className="shrink-0 text-[10px] tabular-nums text-text-tertiary">
                      {sym.blast}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
