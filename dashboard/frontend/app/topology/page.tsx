"use client";

import { useMemo, useState } from "react";
import { useQuery } from "urql";
import { TOPOLOGY_FULL_QUERY } from "@/lib/graphql/queries/topology";
import { EdgeBundling } from "@/components/topology/edge-bundling";
import { CodeTreemap } from "@/components/topology/code-treemap";
import { CardSkeleton } from "@/components/shared/loading-skeleton";

type ViewMode = "treemap" | "bundling";

/**
 * Compute what fraction of edges cross between top-level directories.
 * High ratio → edge bundling is visually interesting.
 * Low ratio → treemap is more informative.
 */
function crossDirRatio(
  nodes: Array<{ id: string; file: string }>,
  edges: Array<{ source: string; target: string }>
): number {
  const nodeDir = new Map<string, string>();
  for (const n of nodes) {
    nodeDir.set(n.id, n.file.split("/")[0]);
  }

  let cross = 0;
  let resolved = 0;
  for (const e of edges) {
    const sd = nodeDir.get(e.source);
    const td = nodeDir.get(e.target);
    if (!sd || !td) continue;
    resolved++;
    if (sd !== td) cross++;
  }

  return resolved > 0 ? cross / resolved : 0;
}

export default function TopologyPage() {
  const [{ data, fetching, error }] = useQuery({ query: TOPOLOGY_FULL_QUERY });
  const [viewOverride, setViewOverride] = useState<ViewMode | null>(null);

  // Auto-select based on data characteristics
  const autoView = useMemo<ViewMode>(() => {
    if (!data?.codebaseTopology) return "treemap";
    const ratio = crossDirRatio(
      data.codebaseTopology.nodes,
      data.codebaseTopology.edges
    );
    // If >20% of edges span directories, the bundling will look dramatic
    return ratio > 0.2 ? "bundling" : "treemap";
  }, [data]);

  const activeView = viewOverride ?? autoView;

  if (fetching) {
    return (
      <div className="grid gap-4 md:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <CardSkeleton key={i} />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="surface p-4 text-red">
        Error: {error.message}
      </div>
    );
  }

  const topo = data?.codebaseTopology;
  if (!topo) {
    return (
      <div className="text-text-secondary">
        No topology data. Run{" "}
        <code className="rounded bg-bg-card px-1.5 py-0.5 text-accent">
          speed init
        </code>{" "}
        to build the semantic graph.
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col gap-4">
      {/* Stats bar + view toggle */}
      <div className="surface flex items-center gap-8 px-5 py-3">
        <Stat label="Symbols" value={topo.nodeCount} accent />
        <Stat label="Edges" value={topo.edgeCount} />
        <Stat label="Clusters" value={topo.clusterCount} />

        {/* View toggle */}
        <div className="ml-auto flex items-center gap-1 rounded-lg border border-border bg-bg p-0.5">
          <ToggleButton
            active={activeView === "treemap"}
            onClick={() => setViewOverride("treemap")}
          >
            Treemap
          </ToggleButton>
          <ToggleButton
            active={activeView === "bundling"}
            onClick={() => setViewOverride("bundling")}
          >
            Dependency Ring
          </ToggleButton>
        </div>
      </div>

      {/* Visualization */}
      <div className="surface flex-1 overflow-hidden" style={{ minHeight: 600 }}>
        {activeView === "bundling" ? (
          <EdgeBundling
            nodes={topo.nodes}
            edges={topo.edges}
            clusters={topo.clusters}
          />
        ) : (
          <CodeTreemap nodes={topo.nodes} clusters={topo.clusters} />
        )}
      </div>
    </div>
  );
}

/* ── Sub-components ────────────────────────────────────────────── */

function Stat({
  label,
  value,
  accent,
}: {
  label: string;
  value: number;
  accent?: boolean;
}) {
  return (
    <div className="flex items-baseline gap-2">
      <span
        className="text-[18px] font-semibold tabular-nums"
        style={{
          fontFamily: "var(--font-mono)",
          color: accent ? "var(--color-accent)" : "var(--color-text)",
        }}
      >
        {value.toLocaleString()}
      </span>
      <span className="type-kpi-label">{label}</span>
    </div>
  );
}

function ToggleButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded-md px-3 py-1.5 text-[11px] font-medium transition-colors ${
        active
          ? "bg-bg-card text-text shadow-sm"
          : "text-text-tertiary hover:text-text-secondary"
      }`}
      style={{ fontFamily: "var(--font-mono)" }}
    >
      {children}
    </button>
  );
}
