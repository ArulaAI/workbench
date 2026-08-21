"use client";

import { useState, useEffect } from "react";
import type { ContextPackage } from "@/lib/graphql/queries/ceremony";

/* ── Helpers ───────────────────────────────────────────────── */

function relativeTime(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const seconds = Math.floor(ms / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function countSources(pkg: ContextPackage): number {
  const keys = Object.keys(pkg.sourcesStatus ?? {});
  return keys.length || 7; // fallback to 7 if sourcesStatus is empty
}

function hasWarnings(pkg: ContextPackage): boolean {
  const visionBad =
    pkg.visionStatus === "missing" || pkg.visionStatus === "stale";
  const anyError = Object.values(pkg.sourcesStatus ?? {}).some(
    (s) => s === "error"
  );
  const lowConf = (pkg as any).lowConfidence === true;
  return visionBad || anyError || lowConf;
}

function warningMessages(pkg: ContextPackage): string[] {
  const msgs: string[] = [];
  if ((pkg as any).lowConfidence) {
    const method = (pkg as any).scopingMethod || "unknown";
    msgs.push(
      method === "full_graph"
        ? "Scoping fell back to full graph. The scope may include irrelevant files. Try refining the intent with more specific terms."
        : "Scoping confidence is low. Over 40% of the codebase matched. Consider refining the intent."
    );
  }
  if (pkg.visionStatus === "missing")
    msgs.push("Product vision is missing. Vision alignment cannot be verified.");
  if (pkg.visionStatus === "stale")
    msgs.push(
      "Product vision is stale. Vision alignment cannot be verified."
    );
  for (const [source, status] of Object.entries(pkg.sourcesStatus ?? {})) {
    if (status === "error") msgs.push(`${source} source returned an error.`);
  }
  return msgs;
}

/* ── Types ─────────────────────────────────────────────────── */

interface BlufViewProps {
  featureName: string;
  contextPackage: ContextPackage;
  assembledAt: string;
  onDismiss: () => void;
}

/* ── Severity / confidence badge ───────────────────────────── */

function SeverityBadge({ severity }: { severity: string }) {
  const s = severity.toLowerCase();
  let color = "var(--color-text-tertiary)";
  let bg = "rgba(85, 85, 106, 0.12)";
  if (s === "critical") {
    color = "var(--color-red)";
    bg = "rgba(239, 68, 100, 0.12)";
  } else if (s === "major") {
    color = "var(--color-amber)";
    bg = "rgba(240, 178, 50, 0.12)";
  }
  return (
    <span
      style={{
        display: "inline-block",
        fontFamily: "var(--font-sans)",
        fontSize: 10,
        fontWeight: 500,
        padding: "1px 5px",
        borderRadius: 3,
        color,
        background: bg,
        flexShrink: 0,
        marginTop: 2,
      }}
    >
      {s}
    </span>
  );
}

function ConfidenceBadge({ confidence }: { confidence: string }) {
  const c = confidence.toLowerCase();
  let color = "var(--color-text-tertiary)";
  let bg = "rgba(85, 85, 106, 0.12)";
  if (c === "high") {
    color = "var(--color-emerald)";
    bg = "rgba(68, 204, 119, 0.12)";
  } else if (c === "medium") {
    color = "var(--color-amber)";
    bg = "rgba(240, 178, 50, 0.12)";
  }
  return (
    <span
      style={{
        display: "inline-block",
        fontFamily: "var(--font-sans)",
        fontSize: 10,
        fontWeight: 500,
        padding: "1px 5px",
        borderRadius: 3,
        color,
        background: bg,
        flexShrink: 0,
        marginTop: 2,
      }}
    >
      {c}
    </span>
  );
}

/* ── Warning icon (circle-exclamation) ─────────────────────── */

function WarningIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      style={{ color: "var(--color-red)", flexShrink: 0, marginTop: 1 }}
    >
      <circle cx="12" cy="12" r="10" />
      <line x1="12" y1="8" x2="12" y2="12" />
      <line x1="12" y1="16" x2="12.01" y2="16" />
    </svg>
  );
}

/* ── Markdown export ──────────────────────────────────────── */

function contextToMarkdown(pkg: ContextPackage): string {
  const lines: string[] = [];
  lines.push(`# Context Brief: ${(pkg as any).featureName || "feature"}`);
  lines.push("");
  lines.push(`> ${pkg.intent}`);
  lines.push("");

  const bluf = (pkg as any).blufSummary;
  if (bluf) {
    lines.push("## Summary");
    lines.push("");
    lines.push(bluf);
    lines.push("");
  }

  if (pkg.defects.length > 0) {
    lines.push("## Defects");
    lines.push("");
    for (const d of pkg.defects) {
      lines.push(`- **[${d.severity}]** ${d.name}`);
    }
    lines.push("");
  }

  if (pkg.learnings.length > 0) {
    lines.push("## Learnings");
    lines.push("");
    for (const l of pkg.learnings) {
      lines.push(`- [${l.confidence}] ${l.text}`);
    }
    lines.push("");
  }

  if (pkg.relatedFeatures.length > 0) {
    lines.push("## Related Features");
    lines.push("");
    for (const r of pkg.relatedFeatures) {
      lines.push(`- **${r.name}** (${r.state}) — ${r.overlapFiles.length} shared files`);
    }
    lines.push("");
  }

  if (pkg.auditHistory.length > 0) {
    lines.push("## Audit Findings");
    lines.push("");
    for (const a of pkg.auditHistory) {
      lines.push(`- **[${a.severity}]** ${a.finding}`);
    }
    lines.push("");
  }

  // Scoped files grouped by directory
  const byDir = new Map<string, string[]>();
  for (const c of pkg.codebase) {
    const parts = c.path.split("/");
    const dir = parts.slice(0, -1).join("/") || ".";
    const group = byDir.get(dir) ?? [];
    group.push(parts[parts.length - 1]);
    byDir.set(dir, group);
  }
  if (byDir.size > 0) {
    lines.push("## Scoped Files");
    lines.push("");
    for (const [dir, files] of Array.from(byDir.entries()).sort()) {
      const unique = [...new Set(files)];
      lines.push(`- \`${dir}/\` — ${unique.join(", ")}`);
    }
    lines.push("");
  }

  return lines.join("\n");
}

/* ── Component ─────────────────────────────────────────────── */

export function BlufView({
  featureName,
  contextPackage: pkg,
  assembledAt,
  onDismiss,
}: BlufViewProps) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    const raf = requestAnimationFrame(() => setMounted(true));
    return () => cancelAnimationFrame(raf);
  }, []);

  const [copied, setCopied] = useState(false);
  const sourceCount = countSources(pkg);
  const fileCount = pkg.codebase.length;
  const showWarnings = hasWarnings(pkg);
  const warnings = warningMessages(pkg);

  const criticalDefects = pkg.defects.filter(
    (d) => d.severity.toLowerCase() === "critical"
  );
  const nonCriticalDefects = pkg.defects.filter(
    (d) => d.severity.toLowerCase() !== "critical"
  );
  const allDefects = [...criticalDefects, ...nonCriticalDefects];

  const highConfLearnings = pkg.learnings.filter(
    (l) => l.confidence.toLowerCase() === "high"
  );

  // Group codebase items by file for the "Scoped to" section
  const scopedFiles: [string, typeof pkg.codebase][] = (() => {
    const byFile = new Map<string, typeof pkg.codebase>();
    for (const c of pkg.codebase) {
      const group = byFile.get(c.path) ?? [];
      group.push(c);
      byFile.set(c.path, group);
    }
    // Sort by symbol count descending so the most relevant files are shown first
    return Array.from(byFile.entries()).sort((a, b) => b[1].length - a[1].length);
  })();

  // Build clear lines from empty sources
  const clearLines: string[] = [];
  if (pkg.relatedFeatures.length === 0)
    clearLines.push("No related features in this area");
  if (pkg.auditHistory.length === 0)
    clearLines.push("No prior audit findings");
  if (pkg.learnings.length === 0)
    clearLines.push("No learnings from past features");
  if (pkg.defects.length === 0) clearLines.push("No known defects");

  return (
    <div style={{
      ...styles.outer,
      opacity: mounted ? 1 : 0,
      transform: mounted ? "translateY(0)" : "translateY(12px)",
      transition: "opacity 0.4s ease-out, transform 0.4s ease-out",
    }}>
      <div style={styles.inner}>
        {/* ── Anchor ──────────────────────────────────────── */}
        <div style={styles.featureName}>{featureName}</div>
        <div style={styles.intentText}>{pkg.intent}</div>
        <div style={styles.meta}>
          {sourceCount} sources assembled · {scopedFiles.length} file{scopedFiles.length !== 1 ? "s" : ""} scoped
          {(pkg as any).scopingMethod ? ` · ${(pkg as any).scopingMethod}` : ""} ·{" "}
          {relativeTime(assembledAt)}
        </div>

        {/* ── Divider ─────────────────────────────────────── */}
        <div style={styles.divider} />

        {/* ── Synthesized brief ──────────────────────────── */}
        {(pkg as any).blufSummary ? (
          <div style={styles.synthesis}>
            {(pkg as any).blufSummary.split("\n\n").map((para: string, i: number) => (
              <p key={i} style={styles.synthesisPara}>{para}</p>
            ))}
          </div>
        ) : (
          <div style={styles.synthesisPending}>
            <span style={styles.synthesisDot} />
            Synthesizing intelligence brief...
          </div>
        )}

        {/* ── Warnings ────────────────────────────────────── */}
        {showWarnings &&
          warnings.map((msg, i) => (
            <div key={i} style={styles.warning}>
              <WarningIcon />
              <span style={styles.warningText}>{msg}</span>
            </div>
          ))}

        {/* ── Defects ─────────────────────────────────────── */}
        <div style={styles.section}>
          <div style={styles.sectionTitle}>Defects in this area</div>
          {allDefects.map((d, i) => (
            <div key={i} style={styles.item}>
              <SeverityBadge severity={d.severity} />
              <span>{d.name}</span>
            </div>
          ))}
          {criticalDefects.length === 0 && (
            <div style={styles.clearItem}>
              <span style={styles.clearDot} />
              <span>No critical defects</span>
            </div>
          )}
        </div>

        {/* ── Learnings ───────────────────────────────────── */}
        {highConfLearnings.length > 0 && (
          <div style={styles.section}>
            <div style={styles.sectionTitle}>Learnings from past features</div>
            {highConfLearnings.map((l, i) => (
              <div key={i} style={styles.item}>
                <ConfidenceBadge confidence={l.confidence} />
                <span>{l.text}</span>
              </div>
            ))}
          </div>
        )}

        {/* ── Scoped to ───────────────────────────────────── */}
        {pkg.codebase.length > 0 && (
          <div style={styles.section}>
            <div style={styles.sectionTitle}>
              Scoped to · {scopedFiles.length} file{scopedFiles.length !== 1 ? "s" : ""}
            </div>
            {scopedFiles.slice(0, 12).map(([file, symbols]) => (
              <div key={file} style={styles.fileRow}>
                <code style={styles.codePath}>{file}</code>
                <span style={{ color: "var(--color-text-tertiary)", fontSize: 11 }}>
                  {symbols.length} symbol{symbols.length !== 1 ? "s" : ""}
                </span>
              </div>
            ))}
            {scopedFiles.length > 12 && (
              <div style={{
                fontSize: 11,
                color: "var(--color-text-tertiary)",
                marginTop: 4,
              }}>
                +{scopedFiles.length - 12} more files
              </div>
            )}
          </div>
        )}

        {/* ── Clear ───────────────────────────────────────── */}
        {clearLines.length > 0 && (
          <div style={styles.section}>
            <div style={styles.sectionTitle}>Clear</div>
            {clearLines.map((line, i) => (
              <div key={i} style={styles.clearItem}>
                <span style={styles.clearDot} />
                <span>{line}</span>
              </div>
            ))}
          </div>
        )}

        {/* ── Actions ─────────────────────────────────────── */}
        <div style={styles.startRow}>
          <button
            style={styles.copyButton}
            onClick={() => {
              const md = contextToMarkdown(pkg);
              navigator.clipboard.writeText(md);
              setCopied(true);
              setTimeout(() => setCopied(false), 2000);
            }}
          >
            {copied ? "Copied" : "Copy as markdown"}
          </button>
          <button style={styles.startButton} onClick={onDismiss}>
            Start writing
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── Styles ─────────────────────────────────────────────────── */

const styles: Record<string, React.CSSProperties> = {
  outer: {
    flex: 1,
    overflowY: "auto",
    padding: "48px 48px 80px",
  },
  inner: {
    maxWidth: 600,
    margin: "0 auto",
  },
  featureName: {
    fontFamily: "var(--font-mono)",
    fontSize: 12,
    fontWeight: 500,
    color: "var(--color-text-tertiary)",
    marginBottom: 4,
  },
  intentText: {
    fontSize: 15,
    fontWeight: 600,
    color: "var(--color-text)",
    lineHeight: 1.4,
    marginBottom: 8,
  },
  meta: {
    fontSize: 11,
    color: "var(--color-text-tertiary)",
    marginBottom: 32,
  },
  divider: {
    width: "40%",
    height: 1,
    background: "var(--color-border)",
    margin: "0 auto 32px",
  },

  /* Synthesized brief */
  synthesis: {
    marginBottom: 32,
  },
  synthesisPara: {
    fontFamily: "var(--font-sans)",
    fontSize: 14,
    fontWeight: 400,
    color: "var(--color-text-secondary)",
    lineHeight: 1.65,
    marginBottom: 12,
  },

  synthesisPending: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    fontSize: 13,
    color: "var(--color-text-tertiary)",
    marginBottom: 32,
    fontStyle: "italic",
  },
  synthesisDot: {
    width: 6,
    height: 6,
    borderRadius: "50%",
    background: "var(--color-text-tertiary)",
    animation: "dot-pulse 1.2s ease-in-out infinite",
    flexShrink: 0,
  },

  /* Warnings */
  warning: {
    display: "flex",
    alignItems: "flex-start",
    gap: 8,
    padding: "10px 12px",
    background: "rgba(239, 68, 100, 0.06)",
    borderRadius: 6,
    marginBottom: 24,
  },
  warningText: {
    fontSize: 13,
    color: "var(--color-red)",
    lineHeight: 1.5,
  },

  /* Sections */
  section: {
    marginBottom: 24,
  },
  sectionTitle: {
    fontFamily: "var(--font-mono)",
    fontSize: 11,
    fontWeight: 500,
    color: "var(--color-text-tertiary)",
    textTransform: "uppercase" as const,
    letterSpacing: "0.04em",
    marginBottom: 8,
  },

  /* Items */
  item: {
    fontSize: 13,
    color: "var(--color-text-secondary)",
    lineHeight: 1.6,
    marginBottom: 6,
    display: "flex",
    alignItems: "flex-start",
    gap: 8,
  },
  codePath: {
    fontFamily: "var(--font-mono)",
    fontSize: 12,
    color: "var(--color-accent)",
    flexShrink: 0,
  },
  fileRow: {
    fontSize: 13,
    color: "var(--color-text-secondary)",
    lineHeight: 1.6,
    marginBottom: 4,
    display: "flex",
    alignItems: "baseline",
    gap: 8,
  },

  /* Clear items */
  clearItem: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    fontSize: 13,
    color: "var(--color-text-tertiary)",
    marginBottom: 6,
  },
  clearDot: {
    width: 6,
    height: 6,
    borderRadius: "50%",
    background: "var(--color-text-tertiary)",
    flexShrink: 0,
  },

  /* Start button */
  startRow: {
    marginTop: 40,
    display: "flex",
    justifyContent: "center",
    gap: 12,
  },
  copyButton: {
    fontFamily: "var(--font-sans)",
    fontSize: 13,
    fontWeight: 500,
    background: "transparent",
    color: "var(--color-text-tertiary)",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: "var(--color-border)",
    borderRadius: 8,
    padding: "10px 20px",
    cursor: "pointer",
    transition: "color 0.15s, border-color 0.15s",
  },
  startButton: {
    fontFamily: "var(--font-sans)",
    fontSize: 13,
    fontWeight: 600,
    background: "var(--color-accent)",
    color: "var(--color-bg)",
    border: "none",
    borderRadius: 8,
    padding: "10px 28px",
    cursor: "pointer",
    transition: "opacity 0.15s",
  },
};
