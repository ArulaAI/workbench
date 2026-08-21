"use client";

import { useEffect, useRef, useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import type { DefineFeature, DefectData, DefineAggregates } from "@/lib/graphql/queries/define";

export interface ExplorerPanelProps {
  open: boolean;
  onClose: () => void;
  features: DefineFeature[];
  defects: DefectData[];
  aggregates: DefineAggregates;
  projectName?: string;
  branch?: string;
  prefersReducedMotion?: boolean;
}

const MAX_DEFECTS = 4;
const MAX_FEATURES = 10;

const STATE_PRIORITY: Record<string, number> = {
  running: 0,
  executing: 0,
  writing: 1,
  idle: 2,
  completed: 3,
  complete: 3,
  done: 3,
  unplanned: 4,
};

function statePriority(state: string): number {
  return STATE_PRIORITY[state] ?? 4;
}

function specCount(feature: DefineFeature): { have: number; total: number } {
  let have = 0;
  if (feature.specified.productSpec.exists) have++;
  if (feature.specified.technicalSpec.exists) have++;
  if (feature.specified.designSpec.exists) have++;
  return { have, total: 3 };
}

function isComplete(state: string): boolean {
  return state === "complete" || state === "completed" || state === "done" || state === "idle";
}

function severityColor(sev: string): string {
  if (sev === "P0" || sev === "P1") return "var(--color-red)";
  if (sev === "P2") return "var(--color-amber)";
  return "var(--color-text-tertiary)";
}

export function ExplorerPanel({
  open,
  onClose,
  features,
  defects,
  aggregates,
  projectName = "speed",
  branch = "feature/continuous-learning",
  prefersReducedMotion = false,
}: ExplorerPanelProps) {
  const router = useRouter();
  const panelRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const [search, setSearch] = useState("");

  // Save and restore focus around open/close
  useEffect(() => {
    if (open) {
      previousFocusRef.current = document.activeElement as HTMLElement;
      requestAnimationFrame(() => closeButtonRef.current?.focus());
    } else {
      previousFocusRef.current?.focus();
      previousFocusRef.current = null;
    }
  }, [open]);

  // Focus trap + Escape dismiss
  useEffect(() => {
    if (!open) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") { onClose(); return; }
      if (e.key === "Tab" && panelRef.current) {
        const focusable = Array.from(
          panelRef.current.querySelectorAll<HTMLElement>(
            'button:not([disabled]):not([tabindex="-1"]), [href]:not([tabindex="-1"]), input:not([disabled]):not([tabindex="-1"]), [tabindex]:not([tabindex="-1"])',
          ),
        );
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey) {
          if (document.activeElement === first) { e.preventDefault(); last.focus(); }
        } else {
          if (document.activeElement === last) { e.preventDefault(); first.focus(); }
        }
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);

  const [showAllFeatures, setShowAllFeatures] = useState(false);

  const sortedFeatures = useMemo(() => {
    return [...features].sort((a, b) => statePriority(a.state) - statePriority(b.state));
  }, [features]);

  const filteredFeatures = useMemo(() => {
    if (search) {
      const q = search.toLowerCase();
      return sortedFeatures.filter((f) => f.name.toLowerCase().includes(q));
    }
    if (showAllFeatures) return sortedFeatures;
    return sortedFeatures.slice(0, MAX_FEATURES);
  }, [sortedFeatures, search, showAllFeatures]);

  const filteredDefects = useMemo(() => {
    if (!search) return defects;
    const q = search.toLowerCase();
    return defects.filter((d) => d.name.toLowerCase().includes(q));
  }, [defects, search]);

  const transition = prefersReducedMotion ? undefined : "transform 0.2s ease";

  const passCount = features.filter((f) => {
    const s = specCount(f);
    return s.have === s.total;
  }).length;
  const warningCount = aggregates.auditWarningCount;

  return (
    <div
      ref={panelRef}
      role="dialog"
      aria-modal="true"
      aria-label="Document explorer"
      inert={!open || undefined}
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        width: 320,
        height: "100vh",
        zIndex: 100,
        background: "var(--color-bg-elevated)",
        boxShadow: "8px 0 32px rgba(0,0,0,0.4)",
        transform: open ? "translateX(0)" : "translateX(-100%)",
        transition,
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}
    >
      {/* Header */}
      <div style={{ padding: "16px 16px 0", flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
          <div>
            <div style={{ fontFamily: "var(--font-sans)", fontSize: 14, fontWeight: 600, color: "var(--color-text)" }}>
              {projectName}
            </div>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, fontWeight: 400, color: "var(--color-text-tertiary)", marginTop: 2 }}>
              {branch}
            </div>
          </div>
          <button
            ref={closeButtonRef}
            onClick={onClose}
            aria-label="Close document explorer"
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              padding: 4,
              color: "var(--color-text-tertiary)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              borderRadius: 4,
            }}
          >
            <svg width={14} height={14} viewBox="0 0 14 14" fill="none"><path d="M1 1L13 13M13 1L1 13" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" /></svg>
          </button>
        </div>

        {/* Divider */}
        <div style={{ height: 1, background: "var(--color-border)", margin: "12px 0" }} />

        {/* Search */}
        <div style={{ position: "relative", marginBottom: 12 }}>
          <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="var(--color-text-tertiary)" strokeWidth={1.5} style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)" }}>
            <circle cx={11} cy={11} r={8} /><line x1={21} y1={21} x2={16.65} y2={16.65} />
          </svg>
          <input
            type="text"
            placeholder="Search features, defects…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Escape" && search) { e.stopPropagation(); setSearch(""); } }}
            style={{
              width: "100%",
              padding: "7px 10px 7px 30px",
              background: "var(--color-bg)",
              border: "1px solid var(--color-border)",
              borderRadius: 6,
              fontFamily: "var(--font-sans)",
              fontSize: 11,
              color: "var(--color-text)",
              outline: "none",
            }}
          />
        </div>
      </div>

      {/* Scrollable content */}
      <div style={{ flex: 1, overflowY: "auto", padding: "0 0 16px" }}>
        {/* FEATURES */}
        <SectionLabel>FEATURES</SectionLabel>
        {filteredFeatures.length === 0 ? (
          <div style={{ padding: "12px 16px", fontFamily: "var(--font-sans)", fontSize: 11, color: "var(--color-text-tertiary)" }}>
            {search ? "No matches" : "No features"}
          </div>
        ) : (
          filteredFeatures.map((feature) => (
            <FeatureGroup key={feature.name} feature={feature} />
          ))
        )}
        {!search && sortedFeatures.length > MAX_FEATURES && (
          <button
            onClick={() => setShowAllFeatures(!showAllFeatures)}
            style={{
              display: "block",
              width: "100%",
              padding: "6px 16px",
              background: "none",
              border: "none",
              cursor: "pointer",
              fontFamily: "var(--font-sans)",
              fontSize: 11,
              fontWeight: 500,
              color: "var(--color-violet)",
              textAlign: "left",
            }}
          >
            {showAllFeatures ? "Show less" : `Show all ${sortedFeatures.length}`}
          </button>
        )}

        {/* DEFECTS */}
        {(filteredDefects.length > 0 || (!search && defects.length > 0)) && (
          <>
            <SectionLabel>DEFECTS · {search ? filteredDefects.length : defects.length}</SectionLabel>
            {filteredDefects.slice(0, MAX_DEFECTS).map((defect) => (
              <div
                key={defect.name}
                style={{ padding: "4px 16px", display: "flex", alignItems: "center", gap: 8 }}
              >
                <span style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 9,
                  fontWeight: 600,
                  color: severityColor(defect.severity),
                  minWidth: 20,
                }}>
                  {defect.severity}
                </span>
                <span style={{
                  fontFamily: "var(--font-sans)",
                  fontSize: 11,
                  color: "var(--color-text-secondary)",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}>
                  {defect.name}
                </span>
              </div>
            ))}
            {filteredDefects.length > MAX_DEFECTS && (
              <div style={{
                padding: "4px 16px",
                fontFamily: "var(--font-sans)",
                fontSize: 11,
                color: "var(--color-text-tertiary)",
                display: "flex",
                alignItems: "center",
                gap: 8,
              }}>
                <span style={{ minWidth: 20 }} />
                + {filteredDefects.length - MAX_DEFECTS} more
              </div>
            )}
          </>
        )}

        {/* PORTFOLIO AUDIT */}
        {!search && (
          <>
            <SectionLabel>PORTFOLIO AUDIT</SectionLabel>
            <div style={{ padding: "4px 16px", display: "flex", flexDirection: "column", gap: 4 }}>
              <AuditRow
                icon={<svg width={12} height={12} viewBox="0 0 24 24" fill="none" stroke="var(--color-emerald)" strokeWidth={2}><path d="M20 6L9 17l-5-5" /></svg>}
                text={`${passCount} specs pass`}
                color="var(--color-emerald)"
              />
              {warningCount > 0 && (
                <AuditRow
                  icon={<svg width={12} height={12} viewBox="0 0 24 24" fill="none" stroke="var(--color-amber)" strokeWidth={2}><circle cx={12} cy={12} r={10} /><line x1={12} y1={8} x2={12} y2={12} /><line x1={12} y1={16} x2={12.01} y2={16} /></svg>}
                  text={`${warningCount} warning${warningCount !== 1 ? "s" : ""}`}
                  color="var(--color-amber)"
                />
              )}
              <AuditRow
                icon={<svg width={12} height={12} viewBox="0 0 24 24" fill="none" stroke="var(--color-text-tertiary)" strokeWidth={2}><rect x={3} y={3} width={18} height={18} rx={2} /><path d="M3 9h18" /></svg>}
                text={`${aggregates.designSpecCount} of ${aggregates.featureCount} design specs`}
                color="var(--color-text-tertiary)"
              />
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/* ── Section Label ─────────────────────────────────────────────── */

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      padding: "16px 16px 6px",
      fontFamily: "var(--font-mono)",
      fontSize: 9,
      fontWeight: 500,
      color: "var(--color-text-tertiary)",
      textTransform: "uppercase",
      letterSpacing: "0.06em",
    }}>
      {children}
    </div>
  );
}

/* ── Feature Group ─────────────────────────────────────────────── */

function FeatureGroup({ feature }: { feature: DefineFeature }) {
  const [expanded, setExpanded] = useState(false);
  const complete = isComplete(feature.state);
  const { have, total } = specCount(feature);

  const specs = [
    { label: "PRD", key: "productSpec" as const, spec: feature.specified.productSpec },
    { label: "RFC", key: "technicalSpec" as const, spec: feature.specified.technicalSpec },
    { label: "DSN", key: "designSpec" as const, spec: feature.specified.designSpec },
  ];

  return (
    <div>
      <button
        onClick={() => setExpanded(!expanded)}
        style={{
          display: "flex",
          alignItems: "center",
          width: "100%",
          padding: "6px 16px",
          background: "none",
          border: "none",
          cursor: "pointer",
          gap: 6,
          textAlign: "left",
        }}
      >
        {/* Chevron */}
        <svg
          width={10}
          height={10}
          viewBox="0 0 10 10"
          fill="none"
          stroke="var(--color-text-tertiary)"
          strokeWidth={1.5}
          style={{
            flexShrink: 0,
            transform: expanded ? "rotate(90deg)" : "rotate(0deg)",
            transition: "transform 0.1s",
          }}
        >
          <path d="M3 1l4 4-4 4" />
        </svg>

        {/* Name */}
        <span style={{
          flex: 1,
          fontFamily: "var(--font-sans)",
          fontSize: 12,
          fontWeight: 500,
          color: "var(--color-text)",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}>
          {feature.name}
        </span>

        {/* Right side: checkmark or fraction */}
        {complete && have === total ? (
          <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="var(--color-emerald)" strokeWidth={2}>
            <path d="M20 6L9 17l-5-5" />
          </svg>
        ) : have > 0 ? (
          <span style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            fontWeight: 500,
            color: have === total ? "var(--color-emerald)" : "var(--color-amber)",
          }}>
            {have}/{total}
          </span>
        ) : null}
      </button>

      {/* Expanded spec rows */}
      {expanded && (
        <div style={{ paddingLeft: 16 }}>
          {specs.map(({ label, spec }) => (
            <div
              key={label}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "4px 16px",
              }}
            >
              <span style={{
                fontFamily: "var(--font-mono)",
                fontSize: 9,
                fontWeight: 500,
                color: "var(--color-text-tertiary)",
                minWidth: 24,
              }}>
                {label}
              </span>
              {spec.exists ? (
                <>
                  <span style={{
                    width: 5,
                    height: 5,
                    borderRadius: "50%",
                    background: label === "PRD" ? "var(--color-emerald)" : label === "RFC" ? "var(--color-blue)" : "var(--color-violet)",
                    flexShrink: 0,
                  }} />
                  <span style={{
                    fontFamily: "var(--font-sans)",
                    fontSize: 11,
                    color: "var(--color-text-secondary)",
                  }}>
                    {feature.name}
                  </span>
                </>
              ) : (
                <span style={{
                  fontFamily: "var(--font-sans)",
                  fontSize: 11,
                  fontStyle: "italic",
                  color: "var(--color-text-tertiary)",
                }}>
                  + {label === "PRD" ? "product" : label === "RFC" ? "technical" : "design"} spec
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Audit Row ─────────────────────────────────────────────────── */

function AuditRow({ icon, text, color }: { icon: React.ReactNode; text: string; color: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      {icon}
      <span style={{ fontFamily: "var(--font-sans)", fontSize: 11, color }}>{text}</span>
    </div>
  );
}
