"use client";

import { useState } from "react";
import type { DigestEvidence } from "@/lib/graphql/queries/repository-digest";

/** Confidence badge + "N sources" affordance; expands to a list of
 * copyable path:line evidence, with Topology deep links for CSG evidence.
 * See RFC > Dashboard Design > Evidence interaction.
 */
export function EvidenceAffordance({ evidence, clusterId }: { evidence: DigestEvidence[]; clusterId?: string }) {
  const [open, setOpen] = useState(false);
  if (evidence.length === 0) return null;

  return (
    <div style={{ marginTop: 4 }}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
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
            className="surface digest-evidence-panel"
            style={{ padding: 12, display: "flex", flexDirection: "column", gap: 10 }}
          >
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
