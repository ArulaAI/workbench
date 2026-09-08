"use client";

import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "urql";
import { DEFINE_VIEW_QUERY } from "@/lib/graphql/queries/define";
import type {
  DefineViewData,
  DefineFeature,
  DefineAggregates,
} from "@/lib/graphql/queries/define";
import { useFeature } from "@/lib/hooks/use-feature-selector";
import { CardSkeleton } from "@/components/shared/loading-skeleton";
import { VisionWarning } from "@/components/shared/vision-warning";
import { ExplorerPanel } from "@/components/define/explorer-panel";
import { SectionDivider } from "@/components/define/section-divider";
import { DefectRow } from "@/components/define/defect-row";
import { SpecifiedCell } from "@/components/define/specified-cell";
import { BuiltCell } from "@/components/define/built-cell";
import { GapCell } from "@/components/define/gap-cell";
import { IconRail } from "@/components/landing/IconRail";
import { Header } from "@/components/layout/header";
import { DraftsInProgress } from "@/components/ceremony/guided";
import {
  AUTHORING_SESSIONS_QUERY,
  type AuthoringSessionsData,
} from "@/lib/graphql/queries/authoring";

/* ── Toolbar Button ────────────────────────────────────────────── */

function ToolbarButton({
  onClick,
  active,
  icon,
  label,
  shortcut,
}: {
  onClick: () => void;
  active?: boolean;
  icon: React.ReactNode;
  label: string;
  shortcut: string;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "6px 14px",
        borderRadius: 8,
        border: "1px solid var(--color-border)",
        background: active ? "rgba(139, 92, 246, 0.08)" : "transparent",
        color: active ? "var(--color-text)" : "var(--color-text-tertiary)",
        fontFamily: "var(--font-sans)",
        fontSize: 12,
        fontWeight: 500,
        cursor: "pointer",
        transition: "all 0.12s",
      }}
    >
      {icon}
      {label}
      <kbd style={{
        fontFamily: "var(--font-mono)",
        fontSize: 10,
        fontWeight: 500,
        padding: "2px 6px",
        borderRadius: 4,
        background: "var(--color-bg-card)",
        color: "var(--color-text-tertiary)",
      }}>{shortcut}</kbd>
    </button>
  );
}

/* ── Column Header ─────────────────────────────────────────────── */

function ColumnHeader({
  name,
  intent,
  aggregate,
}: {
  name: string;
  intent: string;
  aggregate: string;
}) {
  return (
    <div
      role="columnheader"
      style={{ padding: "16px 20px 12px" }}
    >
      <div className="type-column-name">{name}</div>
      <div className="type-column-intent" style={{ marginTop: 4 }}>
        {intent}
      </div>
      <div className="type-column-aggregate" style={{ marginTop: 4 }}>
        {aggregate}
      </div>
    </div>
  );
}

/* ── Aggregate Helpers ─────────────────────────────────────────── */

function specifiedAggregate(agg: DefineAggregates): string {
  return `${agg.designSpecCount} of ${agg.featureCount} have design specs`;
}

function builtAggregate(agg: DefineAggregates): string {
  return `${agg.completedCount} complete, ${agg.executingCount} executing, ${agg.unplannedCount} unplanned`;
}

function gapAggregate(agg: DefineAggregates): string {
  const featureCount = agg.featureCount;
  const esc = agg.escalationCount;
  return `${esc} escalation${esc !== 1 ? "s" : ""} across ${featureCount} feature${featureCount !== 1 ? "s" : ""}`;
}

/* ── Loading State ─────────────────────────────────────────────── */

function LoadingState({ isCompact }: { isCompact: boolean }) {
  const columns = isCompact ? "1fr" : "1fr 1fr 1fr";
  const skeletonCount = isCompact ? 3 : 9;

  return (
    <div>
      {/* Column headers with placeholder aggregates */}
      <div
        role="grid"
        aria-label="Define view loading"
        style={{
          display: "grid",
          gridTemplateColumns: columns,
          /* 1px gap creates divider lines via the grid's background color */
          gap: 1,
          background: "var(--color-border)",
          borderRadius: 10,
          overflow: "hidden",
        }}
      >
        {!isCompact && (
          <>
            <ColumnHeader name="Specified" intent="What we promised" aggregate="\u2014" />
            <ColumnHeader name="Built" intent="What exists" aggregate="\u2014" />
            <ColumnHeader name="Gap" intent="What's missing" aggregate="\u2014" />
          </>
        )}
      </div>

      {/* Skeleton cards per column */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: columns,
          gap: 16,
          marginTop: 16,
        }}
      >
        {Array.from({ length: skeletonCount }).map((_, i) => (
          <CardSkeleton key={i} />
        ))}
      </div>
    </div>
  );
}

/* ── Error State ───────────────────────────────────────────────── */

function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <div
      className="surface"
      style={{
        padding: 24,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 16,
      }}
    >
      <div
        className="type-body"
        style={{
          color: "var(--color-red)",
          textAlign: "center",
        }}
      >
        {message}
      </div>
      <button
        onClick={onRetry}
        style={{
          fontFamily: "var(--font-sans)",
          fontWeight: 500,
          color: "var(--color-violet)",
          background: "var(--color-violet-glow)",
          border: "1px solid var(--color-violet-glow)",
          borderRadius: 6,
          padding: "8px 20px",
          cursor: "pointer",
          transition: "background 0.15s",
        }}
      >
        Retry
      </button>
    </div>
  );
}

/* ── Empty State ───────────────────────────────────────────────── */

function EmptyState() {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        minHeight: 240,
      }}
    >
      <div
        className="type-body"
        style={{ textAlign: "center", lineHeight: 1.6 }}
      >
        No features found. Run{" "}
        <code
          className="type-column-intent"
          style={{
            fontFamily: "var(--font-mono)",
            background: "var(--color-bg-card)",
            padding: "2px 8px",
            borderRadius: 4,
            color: "var(--color-accent)",
          }}
        >
          speed plan
        </code>{" "}
        to get started.
      </div>
    </div>
  );
}

/* ── Responsive media query hook ───────────────────────────────── */

function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (cb: () => void) => {
      const mql = window.matchMedia(query);
      mql.addEventListener("change", cb);
      return () => mql.removeEventListener("change", cb);
    },
    [query],
  );
  const getSnapshot = () => window.matchMedia(query).matches;
  const getServerSnapshot = () => false;
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}

/* ── Page ──────────────────────────────────────────────────────── */

export default function DefinePage() {
  const router = useRouter();
  const { selectedFeature } = useFeature();
  const [{ data, fetching, error }, reexecute] = useQuery<DefineViewData>({
    query: DEFINE_VIEW_QUERY,
    variables: { feature: selectedFeature },
  });

  // Read-only: --list reads checkpoints and writes nothing.
  const [{ data: draftsData }] = useQuery<AuthoringSessionsData>({
    query: AUTHORING_SESSIONS_QUERY,
    variables: { artifactType: "prd" },
    requestPolicy: "network-only",
  });
  const drafts = draftsData?.authoringSessions?.sessions ?? [];

  const isCompact = useMediaQuery("(max-width: 1023px)");
  const prefersReducedMotion = useMediaQuery(
    "(prefers-reduced-motion: reduce)",
  );

  const [explorerOpen, setExplorerOpen] = useState(false);

  const handleRetry = useCallback(() => {
    reexecute({ requestPolicy: "network-only" });
  }, [reexecute]);

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "e") {
        e.preventDefault();
        setExplorerOpen((prev) => !prev);
      }
      if ((e.metaKey || e.ctrlKey) && e.key === "n") {
        e.preventDefault();
        router.push("/define/new");
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [router]);

  let content: React.ReactNode;

  if (fetching) {
    content = <LoadingState isCompact={isCompact} />;
  } else if (error) {
    content = <ErrorState message={error.message} onRetry={handleRetry} />;
  } else {
    const view = data?.defineView;
    if (!view || view.features.length === 0) {
      content = (
        <>
          {drafts.length > 0 && (
            <div style={{ marginBottom: 24 }}>
              <DraftsInProgress sessions={drafts} />
            </div>
          )}
          <EmptyState />
        </>
      );
    } else {
      content = (
        <DefineContent
          view={view}
          drafts={drafts}
          isCompact={isCompact}
          explorerOpen={explorerOpen}
          setExplorerOpen={setExplorerOpen}
          prefersReducedMotion={prefersReducedMotion}
        />
      );
    }
  }

  return (
    <div style={{ display: "flex", height: "100vh" }}>
      <IconRail />
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <Header actions={
          <>
            <ToolbarButton
              onClick={() => router.push("/define/studio")}
              icon={<span aria-hidden="true">✦</span>}
              label="Authoring studio"
              shortcut="Preview"
            />
            <ToolbarButton
              onClick={() => setExplorerOpen((prev) => !prev)}
              active={explorerOpen}
              icon={<svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}><path d="M3 12h18M3 6h18M3 18h18" /></svg>}
              label="Explorer"
              shortcut="⌘E"
            />
            <ToolbarButton
              onClick={() => router.push("/define/new")}
              icon={<svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}><path d="M12 20h9M16.5 3.5a2.121 2.121 0 013 3L7 19l-4 1 1-4L16.5 3.5z" /></svg>}
              label="New spec"
              shortcut="⌘N"
            />
          </>
        } />
        <main style={{ flex: 1, overflow: "auto", padding: 24 }}>
          {content}
        </main>
      </div>
    </div>
  );

}

function DefineContent({
  view,
  drafts,
  isCompact,
  explorerOpen,
  setExplorerOpen,
  prefersReducedMotion,
}: {
  view: NonNullable<DefineViewData["defineView"]>;
  drafts: AuthoringSessionsData["authoringSessions"]["sessions"];
  isCompact: boolean;
  explorerOpen: boolean;
  setExplorerOpen: (open: boolean) => void;
  prefersReducedMotion: boolean;
}) {
  const { features, defects, aggregates } = view;

  return (
    <div
      style={{
        ...(prefersReducedMotion ? {} : { transition: "opacity 0.15s" }),
      }}
    >
      <ExplorerPanel
        open={explorerOpen}
        onClose={() => setExplorerOpen(false)}
        features={features}
        defects={defects}
        aggregates={aggregates}
        prefersReducedMotion={prefersReducedMotion}
      />

      {/* Vision warning when product vision is missing */}
      {view.visionStatus === "missing" && (
        <div style={{ marginBottom: 20 }}>
          <VisionWarning variant="full" />
        </div>
      )}

      {/* Resumable guided interviews, ahead of the coverage grid */}
      {drafts.length > 0 && (
        <div style={{ marginBottom: 24 }}>
          <DraftsInProgress sessions={drafts} />
        </div>
      )}

      {/* Three-column grid */}
      <div
        role="grid"
        aria-label="Feature define view"
        style={{
          display: "grid",
          gridTemplateColumns: isCompact ? "1fr" : "1fr 1fr 1fr",
          gap: 1,
          background: "var(--color-border)",
          borderRadius: 10,
          overflow: "hidden",
        }}
      >
        {!isCompact && (
          <>
            <ColumnHeader
              name="Specified"
              intent="What we promised"
              aggregate={specifiedAggregate(aggregates)}
            />
            <ColumnHeader
              name="Built"
              intent="What exists"
              aggregate={builtAggregate(aggregates)}
            />
            <ColumnHeader
              name="Gap"
              intent="What's missing"
              aggregate={gapAggregate(aggregates)}
            />
          </>
        )}

        {features.map((feature) => (
          <FeatureRow
            key={feature.name}
            feature={feature}
            isCompact={isCompact}
          />
        ))}
      </div>

      {defects.length > 0 && (
        <>
          <SectionDivider count={defects.length} />
          <div
            style={{
              display: "grid",
              gridTemplateColumns: isCompact ? "1fr" : "1fr 1fr 1fr",
              gap: 1,
              background: "var(--color-border)",
              borderRadius: 10,
              overflow: "hidden",
            }}
          >
            {defects.map((defect) => (
              <DefectRow key={defect.name} defect={defect} isCompact={isCompact} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

/* ── Feature Row ───────────────────────────────────────────────── */

type CellState = "complete" | "executing" | "writing" | "unplanned";

function normalizeCellState(raw: string): CellState {
  switch (raw) {
    case "complete":
    case "completed":
    case "done":
      return "complete";
    case "executing":
    case "running":
      return "executing";
    case "writing":
      return "writing";
    case "idle":
      return "complete";
    default:
      return "unplanned";
  }
}

function FeatureRow({
  feature,
  isCompact,
}: {
  feature: DefineFeature;
  isCompact: boolean;
}) {
  const cellState = normalizeCellState(feature.state);
  if (isCompact) {
    return (
      <div style={{ background: "var(--color-bg)", padding: "12px 20px" }}>
        <div
          className="type-section-header"
          style={{ fontWeight: 500, marginBottom: 8 }}
        >
          {feature.name}
        </div>
        {/* Inline labels for compact view */}
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div>
            <span className="type-compact-label">Specified</span>
            <SpecifiedCell name={feature.name} state={cellState} specified={feature.specified} />
          </div>
          <div>
            <span className="type-compact-label">Built</span>
            <BuiltCell state={cellState} built={feature.built} />
          </div>
          <div>
            <span className="type-compact-label">Gap</span>
            <GapCell state={cellState} gap={feature.gap} />
          </div>
        </div>
      </div>
    );
  }

  return (
    <>
      <SpecifiedCell name={feature.name} state={cellState} specified={feature.specified} />
      <BuiltCell state={cellState} built={feature.built} />
      <GapCell state={cellState} gap={feature.gap} />
    </>
  );
}
