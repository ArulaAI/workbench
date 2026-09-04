"use client";

import { useEffect, useId, useRef, useState } from "react";
import type { DigestEvidence } from "@/lib/graphql/queries/repository-digest";

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** Confidence badge + "N sources" affordance; expands to a list of
 * copyable path:line evidence, with Topology deep links for CSG evidence.
 * See RFC > Dashboard Design > Evidence interaction.
 *
 * The expanded panel is a modal dialog (role="dialog", labelled heading,
 * close button, Escape to close, focus moved in on open and restored to
 * the trigger on close, Tab contained within the panel while open) —
 * not just a floating div, since it visually overlays the page via the
 * scrim the same way a dialog does.
 */
export function EvidenceAffordance({ evidence, clusterId }: { evidence: DigestEvidence[]; clusterId?: string }) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const headingId = useId();

  useEffect(() => {
    if (!open) return;
    const panel = panelRef.current;
    const trigger = triggerRef.current;
    const closeButton = panel?.querySelector<HTMLElement>('[data-evidence-close]');
    closeButton?.focus();

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        setOpen(false);
        return;
      }
      if (e.key !== "Tab" || !panel) return;
      const focusable = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown, true);
    return () => {
      document.removeEventListener("keydown", handleKeyDown, true);
      // Only runs when transitioning out of the open state (this effect
      // never even runs its body while `open` is false, so its cleanup
      // never fires from "was never open") — restores focus to the
      // trigger, never steals it on initial mount.
      trigger?.focus();
    };
  }, [open]);

  if (evidence.length === 0) return null;

  return (
    <div style={{ marginTop: 4 }}>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="type-caption"
        style={{
          background: "none",
          border: "none",
          cursor: "pointer",
          color: "var(--color-text-secondary)",
          padding: 0,
        }}
      >
        {evidence.length} source{evidence.length === 1 ? "" : "s"}
      </button>
      {open && (
        <>
          <div className="digest-evidence-scrim" onClick={() => setOpen(false)} />
          <div
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby={headingId}
            className="surface digest-evidence-panel"
            style={{ padding: 12, display: "flex", flexDirection: "column", gap: 10 }}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
              <div id={headingId} className="type-section-header">
                Evidence
              </div>
              <button
                type="button"
                data-evidence-close
                onClick={() => setOpen(false)}
                aria-label="Close"
                className="type-caption"
                style={{
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  color: "var(--color-text-secondary)",
                  padding: 4,
                  lineHeight: 1,
                }}
              >
                ✕
              </button>
            </div>
            {evidence.map((e, i) => (
              <EvidenceRow key={i} evidence={e} clusterId={clusterId} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function EvidenceRow({ evidence, clusterId }: { evidence: DigestEvidence; clusterId?: string }) {
  const locator = evidence.symbol
    ? evidence.symbol
    : evidence.path
    ? `${evidence.path}${evidence.line ? `:${evidence.line}` : ""}`
    : evidence.artifactKey ?? "";

  const topologyHref = clusterId
    ? `/topology?cluster=${encodeURIComponent(clusterId)}&symbol=${encodeURIComponent(evidence.symbol ?? "")}`
    : `/topology?symbol=${encodeURIComponent(evidence.symbol ?? "")}`;

  return (
    <div>
      <div className="type-table-header" style={{ marginBottom: 2 }}>
        {evidence.source}
      </div>
      {evidence.source === "semantic_graph" && evidence.symbol ? (
        <a
          href={topologyHref}
          className="type-mono-value"
          style={{ color: "var(--color-accent)", textDecoration: "none", wordBreak: "break-word" }}
        >
          {locator}
        </a>
      ) : (
        <button
          type="button"
          onClick={() => navigator.clipboard?.writeText(locator)}
          className="type-mono-value"
          title="Copy"
          style={{ background: "none", border: "none", cursor: "copy", padding: 0, color: "var(--color-text)", wordBreak: "break-word", textAlign: "left" }}
        >
          {locator}
        </button>
      )}
      <div className="type-caption" style={{ marginTop: 2 }}>
        {evidence.description}
      </div>
    </div>
  );
}
