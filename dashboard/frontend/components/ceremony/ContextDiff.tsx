"use client";

import { useState, useMemo } from "react";
import type {
  ContextPackage,
  CodebaseItem,
  LearningItem,
  DefectItem,
  KnowledgeItem,
  RelatedFeature,
  AuditHistoryItem,
} from "@/lib/graphql/queries/ceremony";

/* ── Props ─────────────────────────────────────────────────── */

interface ContextDiffProps {
  snapshot: ContextPackage;
  current: ContextPackage;
}

/* ── Change types ──────────────────────────────────────────── */

type ChangeKind = "new" | "removed" | "changed" | "unchanged";

interface DiffEntry {
  kind: ChangeKind;
  label: string;
  detail?: string;
}

interface SectionDiff {
  title: string;
  entries: DiffEntry[];
  changeCount: number;
}

/* ── Badge helpers ─────────────────────────────────────────── */

const CHANGE_BADGES: Record<ChangeKind, React.CSSProperties> = {
  new: {
    display: "inline-block",
    fontFamily: "var(--font-sans)",
    fontSize: 10,
    fontWeight: 500,
    padding: "1px 5px",
    borderRadius: 3,
    marginRight: 6,
    color: "var(--color-emerald)",
    background: "rgba(68, 204, 119, 0.12)",
  },
  removed: {
    display: "inline-block",
    fontFamily: "var(--font-sans)",
    fontSize: 10,
    fontWeight: 500,
    padding: "1px 5px",
    borderRadius: 3,
    marginRight: 6,
    color: "var(--color-red)",
    background: "rgba(239, 68, 100, 0.12)",
  },
  changed: {
    display: "inline-block",
    fontFamily: "var(--font-sans)",
    fontSize: 10,
    fontWeight: 500,
    padding: "1px 5px",
    borderRadius: 3,
    marginRight: 6,
    color: "var(--color-amber)",
    background: "rgba(240, 178, 50, 0.12)",
  },
  unchanged: {
    display: "none",
  },
};

const CHANGE_LABELS: Record<ChangeKind, string> = {
  new: "New",
  removed: "Removed",
  changed: "Changed",
  unchanged: "",
};

/* ── Diff computation ──────────────────────────────────────── */

function diffByKey<T>(
  snapshotItems: T[],
  currentItems: T[],
  getKey: (item: T) => string,
  getLabel: (item: T) => string,
  getDetail?: (item: T) => string | undefined
): DiffEntry[] {
  const snapshotKeys = new Set(snapshotItems.map(getKey));
  const currentKeys = new Set(currentItems.map(getKey));
  const entries: DiffEntry[] = [];

  // New items (in current, not in snapshot)
  for (const item of currentItems) {
    const key = getKey(item);
    if (!snapshotKeys.has(key)) {
      entries.push({
        kind: "new",
        label: getLabel(item),
        detail: getDetail?.(item),
      });
    }
  }

  // Removed items (in snapshot, not in current)
  for (const item of snapshotItems) {
    const key = getKey(item);
    if (!currentKeys.has(key)) {
      entries.push({
        kind: "removed",
        label: getLabel(item),
        detail: getDetail?.(item),
      });
    }
  }

  // Unchanged (in both)
  for (const item of currentItems) {
    const key = getKey(item);
    if (snapshotKeys.has(key)) {
      entries.push({
        kind: "unchanged",
        label: getLabel(item),
        detail: getDetail?.(item),
      });
    }
  }

  return entries;
}

function diffKnowledge(
  snapshotItems: KnowledgeItem[],
  currentItems: KnowledgeItem[]
): DiffEntry[] {
  const snapshotByText = new Map(snapshotItems.map((k) => [k.text, k]));
  const currentByText = new Map(currentItems.map((k) => [k.text, k]));
  const entries: DiffEntry[] = [];

  // Check for new, changed, and unchanged
  for (const item of currentItems) {
    if (snapshotByText.has(item.text)) {
      entries.push({
        kind: "unchanged",
        label: item.text,
        detail: item.source,
      });
    } else {
      // Check if a similar entry exists (first 20 chars match)
      const prefix = item.text.slice(0, 20);
      const similar = snapshotItems.find(
        (s) => s.text.slice(0, 20) === prefix && !currentByText.has(s.text)
      );
      if (similar) {
        entries.push({
          kind: "changed",
          label: item.text,
          detail: item.source,
        });
      } else {
        entries.push({
          kind: "new",
          label: item.text,
          detail: item.source,
        });
      }
    }
  }

  // Removed: in snapshot but not in current (and not already matched as "changed")
  const matchedPrefixes = new Set(
    entries
      .filter((e) => e.kind === "changed")
      .map((e) => e.label.slice(0, 20))
  );
  for (const item of snapshotItems) {
    if (!currentByText.has(item.text)) {
      const prefix = item.text.slice(0, 20);
      if (!matchedPrefixes.has(prefix)) {
        entries.push({
          kind: "removed",
          label: item.text,
          detail: item.source,
        });
      }
    }
  }

  return entries;
}

function diffVision(
  snapshot: ContextPackage,
  current: ContextPackage
): DiffEntry[] {
  if (snapshot.visionStatus === current.visionStatus) {
    return [
      {
        kind: "unchanged",
        label: `Vision: ${current.visionStatus}`,
      },
    ];
  }
  return [
    {
      kind: "changed",
      label: `Vision was ${snapshot.visionStatus}, now ${current.visionStatus}`,
    },
  ];
}

function computeDiff(
  snapshot: ContextPackage,
  current: ContextPackage
): SectionDiff[] {
  const sections: SectionDiff[] = [];

  // 1. Codebase
  const codebaseEntries = diffByKey<CodebaseItem>(
    snapshot.codebase,
    current.codebase,
    (item) => item.path,
    (item) => item.path,
    (item) => item.description
  );
  sections.push({
    title: "Codebase",
    entries: codebaseEntries,
    changeCount: codebaseEntries.filter((e) => e.kind !== "unchanged").length,
  });

  // 2. Learnings
  const learningEntries = diffByKey<LearningItem>(
    snapshot.learnings,
    current.learnings,
    (item) => item.text,
    (item) => item.text,
    (item) => `from ${item.sourceFeature}`
  );
  sections.push({
    title: "Learnings",
    entries: learningEntries,
    changeCount: learningEntries.filter((e) => e.kind !== "unchanged").length,
  });

  // 3. Defects
  const defectEntries = diffByKey<DefectItem>(
    snapshot.defects,
    current.defects,
    (item) => item.name,
    (item) => item.name
  );
  sections.push({
    title: "Defects",
    entries: defectEntries,
    changeCount: defectEntries.filter((e) => e.kind !== "unchanged").length,
  });

  // 4. Project Knowledge (with "changed" detection)
  const knowledgeEntries = diffKnowledge(
    snapshot.projectKnowledge,
    current.projectKnowledge
  );
  sections.push({
    title: "Project Knowledge",
    entries: knowledgeEntries,
    changeCount: knowledgeEntries.filter((e) => e.kind !== "unchanged").length,
  });

  // 5. Vision
  const visionEntries = diffVision(snapshot, current);
  sections.push({
    title: "Vision",
    entries: visionEntries,
    changeCount: visionEntries.filter((e) => e.kind !== "unchanged").length,
  });

  // 6. Related Features
  const relatedEntries = diffByKey<RelatedFeature>(
    snapshot.relatedFeatures,
    current.relatedFeatures,
    (item) => item.name,
    (item) => item.name,
    (item) => item.state
  );
  sections.push({
    title: "Related Features",
    entries: relatedEntries,
    changeCount: relatedEntries.filter((e) => e.kind !== "unchanged").length,
  });

  // 7. Audit History
  const auditEntries = diffByKey<AuditHistoryItem>(
    snapshot.auditHistory,
    current.auditHistory,
    (item) => item.finding,
    (item) => item.finding,
    (item) => `${item.featureName} \u00b7 ${item.section}`
  );
  sections.push({
    title: "Audit History",
    entries: auditEntries,
    changeCount: auditEntries.filter((e) => e.kind !== "unchanged").length,
  });

  return sections;
}

/* ── DiffSection component ─────────────────────────────────── */

function DiffSection({
  title,
  entries,
  changeCount,
}: {
  title: string;
  entries: DiffEntry[];
  changeCount: number;
}) {
  const hasChanges = changeCount > 0;
  const [open, setOpen] = useState(hasChanges);

  return (
    <div style={{ marginBottom: 4 }}>
      <div
        onClick={() => setOpen((o) => !o)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          cursor: "pointer",
          padding: "4px 0",
          userSelect: "none",
        }}
      >
        <svg
          width={10}
          height={10}
          viewBox="0 0 10 10"
          style={{
            flexShrink: 0,
            transition: "transform 0.15s",
            transform: open ? "rotate(90deg)" : "rotate(0deg)",
          }}
        >
          <path
            d="M3 1.5L7 5L3 8.5"
            fill="none"
            stroke="var(--color-text-tertiary)"
            strokeWidth={1.5}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>

        <span
          style={{
            fontFamily: "var(--font-sans)",
            fontSize: 13,
            fontWeight: 600,
            color: hasChanges
              ? "var(--color-text)"
              : "var(--color-text-tertiary)",
            flex: 1,
            minWidth: 0,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {title}
        </span>

        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 13,
            fontWeight: 500,
            color: hasChanges
              ? "var(--color-text-secondary)"
              : "var(--color-text-tertiary)",
            flexShrink: 0,
          }}
        >
          {hasChanges ? changeCount : "No changes"}
        </span>
      </div>

      {open && (
        <div
          style={{
            paddingLeft: 16,
            paddingTop: 4,
            display: "flex",
            flexDirection: "column",
            gap: 6,
          }}
        >
          {entries.map((entry, i) => (
            <div
              key={i}
              style={{
                display: "flex",
                alignItems: "flex-start",
              }}
            >
              {entry.kind !== "unchanged" && (
                <span style={CHANGE_BADGES[entry.kind]}>
                  {CHANGE_LABELS[entry.kind]}
                </span>
              )}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div
                  style={{
                    fontFamily: "var(--font-sans)",
                    fontSize: 12,
                    fontWeight: 400,
                    color:
                      entry.kind === "removed"
                        ? "var(--color-text-tertiary)"
                        : entry.kind === "unchanged"
                        ? "var(--color-text-tertiary)"
                        : "var(--color-text-secondary)",
                    lineHeight: 1.4,
                    textDecoration:
                      entry.kind === "removed" ? "line-through" : "none",
                  }}
                >
                  {entry.label}
                </div>
                {entry.detail && (
                  <div
                    style={{
                      fontFamily: "var(--font-sans)",
                      fontSize: 10,
                      fontWeight: 400,
                      color: "var(--color-text-tertiary)",
                      marginTop: 2,
                    }}
                  >
                    {entry.detail}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Main component ────────────────────────────────────────── */

export function ContextDiff({ snapshot, current }: ContextDiffProps) {
  const sections = useMemo(
    () => computeDiff(snapshot, current),
    [snapshot, current]
  );

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        background: "var(--color-bg-card)",
        overflow: "hidden",
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: "16px 20px",
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          fontWeight: 500,
          color: "var(--color-text-tertiary)",
          textTransform: "uppercase",
          letterSpacing: "0.04em",
          flexShrink: 0,
        }}
      >
        CHANGES SINCE SNAPSHOT
      </div>

      {/* Scrollable diff sections */}
      <div
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "0 16px 16px",
        }}
      >
        {sections.map((section) => (
          <DiffSection
            key={section.title}
            title={section.title}
            entries={section.entries}
            changeCount={section.changeCount}
          />
        ))}
      </div>
    </div>
  );
}
