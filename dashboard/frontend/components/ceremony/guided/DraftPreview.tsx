"use client";

import React, { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { SectionProvenanceEntry } from "@/lib/graphql/queries/authoring";

/**
 * Read-only rendering of the generated artifact with per-section provenance.
 *
 * Section boundaries come from the helper's `sections` array, not from parsing
 * prose: the PRD renderer emits no per-question headings, so a regex over the
 * document would mis-attribute Edit actions.
 */

interface RenderedSection {
  title: string;
  body: string;
  provenance: SectionProvenanceEntry | null;
}

export function splitSections(
  content: string,
  sections: SectionProvenanceEntry[],
): { header: string; rendered: RenderedSection[] } {
  const byTitle = new Map(sections.map((section) => [section.title, section]));
  const lines = content.split("\n");
  const header: string[] = [];
  const rendered: RenderedSection[] = [];
  let current: RenderedSection | null = null;

  for (const line of lines) {
    const match = /^##\s+(.*)$/.exec(line);
    if (match) {
      if (current) rendered.push(current);
      const title = match[1].trim();
      current = { title, body: "", provenance: byTitle.get(title) ?? null };
      continue;
    }
    if (current) {
      current.body += `${line}\n`;
    } else {
      header.push(line);
    }
  }
  if (current) rendered.push(current);
  return { header: header.join("\n"), rendered };
}

export function SectionProvenance({
  section,
  onEdit,
}: {
  section: SectionProvenanceEntry;
  onEdit: (coverageId: string) => void;
}) {
  const ids = section.question_ids ?? [];
  if (ids.length === 0) return null;
  const shown = ids.slice(0, 4);
  const target = section.coverage_ids?.[0] ?? ids[0];
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        marginTop: 8,
        padding: "6px 0",
        borderTop: "1px solid var(--color-border-light)",
      }}
    >
      <span
        title={ids.join(", ")}
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          fontWeight: 500,
          color: "var(--color-text-tertiary)",
        }}
      >
        {shown.join(" · ")}
        {ids.length > shown.length ? ` +${ids.length - shown.length}` : ""}
      </span>
      <button
        type="button"
        className="type-caption"
        onClick={() => onEdit(target)}
        aria-label={`Edit the answer behind ${section.title}, question ${ids.join(", ")}`}
        style={{
          marginLeft: "auto",
          background: "transparent",
          border: "none",
          padding: 0,
          color: "var(--color-text-secondary)",
          fontWeight: 500,
          cursor: "pointer",
        }}
      >
        Edit
      </button>
    </div>
  );
}

export function DraftPreview({
  content,
  sections,
  artifactPath,
  revision,
  highlightQuestionId,
  onEditSection,
}: {
  content: string;
  sections: SectionProvenanceEntry[];
  artifactPath: string | null;
  revision: number | null;
  highlightQuestionId?: string | null;
  onEditSection: (coverageId: string) => void;
}) {
  const { header, rendered } = useMemo(
    () => splitSections(content, sections),
    [content, sections],
  );

  return (
    <section
      className="surface"
      aria-label={`Generated PRD, revision ${revision ?? "unknown"}`}
      style={{
        width: 420,
        flexShrink: 0,
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          height: 32,
          padding: "0 12px",
          background: "var(--color-bg-elevated)",
          borderBottom: "1px solid var(--color-border)",
          flexShrink: 0,
        }}
      >
        <span className="type-mono-value" style={{ color: "var(--color-text-secondary)" }}>
          PRD · rev {revision ?? "-"}
        </span>
        {artifactPath && (
          <a
            className="type-caption"
            href={`/editor?path=${encodeURIComponent(artifactPath)}`}
            style={{ color: "var(--color-text-secondary)", textDecoration: "none" }}
          >
            {artifactPath} ↗
          </a>
        )}
      </div>
      <div
        className="spec-preview"
        key={revision ?? "none"}
        style={{ flex: 1, overflow: "auto", padding: 24 }}
        aria-live="polite"
      >
        <style>{`
          .spec-preview { color: var(--color-text-secondary); font-family: var(--font-sans); font-size: 13px; line-height: 1.7; }
          .spec-preview h1 { color: var(--color-text); font-family: var(--font-mono); font-size: 18px; font-weight: 600; margin: 0 0 16px 0; }
          .spec-preview h2 { color: var(--color-text); font-family: var(--font-mono); font-size: 15px; font-weight: 600; margin: 0 0 12px 0; }
          .spec-preview p { margin: 0 0 12px 0; }
          .spec-preview table { border-collapse: collapse; margin: 0 0 12px 0; }
          .spec-preview th, .spec-preview td { border: 1px solid var(--color-border); padding: 6px 8px; text-align: left; }
          .spec-preview code { font-family: var(--font-mono); font-size: 11px; }
          @media (prefers-reduced-motion: reduce) {
            .guided-section-highlight { transition: none; }
          }
        `}</style>
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{header}</ReactMarkdown>
        {rendered.map((section) => {
          const highlighted =
            Boolean(highlightQuestionId) &&
            (section.provenance?.question_ids ?? []).includes(
              highlightQuestionId as string,
            );
          return (
            <div
              key={section.title}
              id={`section-${section.title.replace(/[^a-zA-Z0-9]+/g, "-").toLowerCase()}`}
              className="guided-section-highlight"
              style={{
                marginBottom: 20,
                padding: highlighted ? 8 : 0,
                margin: highlighted ? "-8px -8px 12px -8px" : undefined,
                borderRadius: 6,
                background: highlighted ? "var(--color-accent-dim)" : "transparent",
                transition: "background 240ms ease-in-out",
              }}
            >
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {`## ${section.title}\n\n${section.body}`}
              </ReactMarkdown>
              {section.provenance && (
                <SectionProvenance section={section.provenance} onEdit={onEditSection} />
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
