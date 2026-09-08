"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Bold, CheckCircle2, Eye, GitCommitHorizontal, Italic, Link, List, ListOrdered, PencilLine, Redo2, Save, Table2, Undo2 } from "lucide-react";
import { SpecEditor, type EditorSelection, type SpecEditorHandle } from "@/components/editor/SpecEditor";
import { SpecPreview } from "@/components/editor/SpecPreview";
import type { SectionProvenanceEntry } from "@/lib/graphql/queries/authoring";

/**
 * Generated artifact rendering with per-section provenance and safe direct edits.
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

function currentDocumentRevision(
  content: string,
  versions: { revision: number; content: string }[],
  sessionRevision: number | null,
): number | null {
  // Document versions and authoring-session revisions usually advance
  // together, but saving a review comment advances only the session. Prefer
  // an exact revision when it exists; otherwise bind the editor to the newest
  // immutable version whose content still matches the current artifact.
  if (
    sessionRevision !== null
    && versions.some((item) => item.revision === sessionRevision)
  ) {
    return sessionRevision;
  }
  const matching = [...versions]
    .sort((a, b) => b.revision - a.revision)
    .find((item) => item.content === content);
  return matching?.revision ?? sessionRevision;
}

export function editableSections(content: string, sections: SectionProvenanceEntry[]): string {
  return splitSections(content, sections).rendered
    .map((section) => `## ${section.title}\n\n${section.body.trim()}`)
    .join("\n\n");
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
  onEditDraft,
  onComment,
  hasComment,
}: {
  section: SectionProvenanceEntry;
  onEditDraft: () => void;
  onComment?: () => void;
  hasComment?: boolean;
}) {
  const ids = section.question_ids ?? [];
  const shown = ids.slice(0, 4);
  const manual = section.state === "manual";
  const reviewed = section.state === "reviewed";
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
        title={ids.length ? `Answer sources: ${ids.join(", ")}` : "Generated section"}
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          fontWeight: 500,
          color: "var(--color-text-tertiary)",
        }}
      >
        {manual
          ? "Manual edit"
          : reviewed
            ? `Review regenerated${ids.length ? ` · From ${shown.join(" · ")}` : ""}`
            : ids.length
              ? `From ${shown.join(" · ")}`
              : "Generated"}
        {!manual && ids.length > shown.length ? ` +${ids.length - shown.length}` : ""}
      </span>
      <button
        type="button"
        className="type-caption"
        onClick={onEditDraft}
        aria-label={`Edit ${section.title} directly in the draft`}
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
        Edit draft
      </button>
      {onComment && (
        <button
          type="button"
          className="type-caption"
          onClick={onComment}
          aria-label={`Add a review comment to ${section.title}`}
          style={{
            marginLeft: 4,
            background: "transparent",
            border: "none",
            padding: 0,
            color: hasComment ? "var(--color-accent)" : "var(--color-text-secondary)",
            fontWeight: 500,
            cursor: "pointer",
          }}
        >
          {hasComment ? "Comment added" : "Comment"}
        </button>
      )}
    </div>
  );
}

export function DraftPreview({
  content,
  sections,
  artifactPath,
  revision,
  highlightQuestionId,
  onEditDraftSection,
  saving = false,
  expanded = false,
  comments = [],
  onAddComment,
  versions = [],
  onSaveDocument,
  onDirtyChange,
  artifactType = "prd",
  artifactLabel = "PRD",
  publishedRevision = null,
  publishing = false,
  onPublish,
  preparingCommit = false,
  onReviewCommit,
}: {
  content: string;
  sections: SectionProvenanceEntry[];
  artifactPath: string | null;
  revision: number | null;
  highlightQuestionId?: string | null;
  onEditDraftSection?: (sectionTitle: string, body: string) => Promise<boolean>;
  saving?: boolean;
  expanded?: boolean;
  comments?: { section_title: string; comment: string }[];
  onAddComment?: (sectionTitle: string, comment: string, anchor?: { selected_text: string; selection_start: number; selection_end: number; anchor_revision: number }) => void;
  versions?: { revision: number; content: string; created_at?: string | null; source?: string | null; status?: string | null; published_at?: string | null }[];
  onSaveDocument?: (content: string) => Promise<boolean>;
  onDirtyChange?: (dirty: boolean) => void;
  artifactType?: string;
  artifactLabel?: string;
  publishedRevision?: number | null;
  publishing?: boolean;
  onPublish?: () => Promise<boolean>;
  preparingCommit?: boolean;
  onReviewCommit?: () => void;
}) {
  const [editingTitle, setEditingTitle] = useState<string | null>(null);
  const [editingBody, setEditingBody] = useState("");
  const [commentingTitle, setCommentingTitle] = useState<string | null>(null);
  const [commentText, setCommentText] = useState("");
  const editorRef = useRef<SpecEditorHandle>(null);
  const documentRevision = useMemo(
    () => currentDocumentRevision(content, versions, revision),
    [content, revision, versions],
  );
  const [selectedRevision, setSelectedRevision] = useState<number | null>(documentRevision);
  const [editorContent, setEditorContent] = useState(() => editableSections(content, sections));
  const [savedEditorContent, setSavedEditorContent] = useState(editorContent);
  const unsavedRef = useRef(false);
  const [selection, setSelection] = useState<EditorSelection | null>(null);
  const [mode, setMode] = useState<"edit" | "view">("edit");
  const { header, rendered } = useMemo(
    () => splitSections(content, sections),
    [content, sections],
  );
  useEffect(() => {
    setEditingTitle(null);
    setCommentingTitle(null);
    setCommentText("");
    setSelectedRevision(documentRevision);
    if (unsavedRef.current) {
      setSelection(null);
      return;
    }
    const next = editableSections(content, sections);
    setEditorContent(next);
    setSavedEditorContent(next);
    setSelection(null);
    setMode("edit");
  }, [documentRevision, revision]);

  const activeVersion = versions.find((item) => item.revision === selectedRevision);
  const versionNumberByRevision = useMemo(
    () => new Map(
      [...versions]
        .sort((a, b) => a.revision - b.revision)
        .map((item, index) => [item.revision, index + 1]),
    ),
    [versions],
  );
  const selectedVersionNumber = versionNumberByRevision.get(
    selectedRevision ?? revision ?? -1,
  ) ?? 1;
  const viewingCurrent = selectedRevision === documentRevision;
  const viewingPublished = viewingCurrent
    ? publishedRevision === documentRevision
    : activeVersion?.status === "published";
  const versionStateLabel = viewingCurrent
    ? (viewingPublished ? "Published" : "Draft")
    : (viewingPublished ? "Published history" : "Draft history");
  const displayedEditorContent = viewingCurrent
    ? editorContent
    : editableSections(activeVersion?.content ?? content, sections);
  const countSource = viewingCurrent ? `${header}\n${editorContent}` : (activeVersion?.content ?? content);
  const displayedDocument = viewingCurrent
    ? `${header.trimEnd()}\n\n${editorContent}`
    : (activeVersion?.content ?? content);
  const wordCount = countSource.trim() ? countSource.trim().split(/\s+/).length : 0;
  const characterCount = countSource.length;
  const hasUnsavedChanges = editorContent !== savedEditorContent;
  unsavedRef.current = hasUnsavedChanges;
  useEffect(() => {
    if (!hasUnsavedChanges) return;
    const preventUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", preventUnload);
    return () => window.removeEventListener("beforeunload", preventUnload);
  }, [hasUnsavedChanges]);
  useEffect(() => {
    onDirtyChange?.(hasUnsavedChanges);
    return () => onDirtyChange?.(false);
  }, [hasUnsavedChanges, onDirtyChange]);
  const reviewCommitDisabled =
    !viewingCurrent || saving || preparingCommit || hasUnsavedChanges;

  if (onSaveDocument) {
    const toolbarButton = (label: string, icon: React.ReactNode, action: () => void, disabled = false) => (
      <button type="button" aria-label={label} title={label} onClick={action} disabled={disabled}
        style={{ width: 30, height: 28, display: "grid", placeItems: "center", border: "none", borderRadius: 4, background: "transparent", color: "var(--color-text-secondary)", cursor: disabled ? "default" : "pointer", opacity: disabled ? 0.35 : 1 }}>
        {icon}
      </button>
    );
    return (
      <section className="surface guided-authoring-preview" aria-label={`Generated ${artifactLabel}, revision ${revision ?? "unknown"}`}
        style={{ minWidth: 0, flex: "1 1 62%", display: "flex", flexDirection: "column", overflow: "hidden", position: "relative" }}>
        <div style={{ minHeight: 42, padding: "6px 10px 6px 14px", display: "flex", alignItems: "center", gap: 8, borderBottom: "1px solid var(--color-border)" }}>
          <span className="type-mono-value">{artifactLabel} · v{selectedVersionNumber} ({versionStateLabel})</span>
          <span className="type-caption" style={{ marginLeft: "auto", fontFamily: "var(--font-mono)", whiteSpace: "nowrap" }}>{wordCount.toLocaleString()} words · {characterCount.toLocaleString()} characters</span>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <button
              type="button"
              aria-pressed={mode === "view"}
              aria-label={mode === "edit" ? "View rendered Markdown" : "Edit Markdown"}
              onClick={() => {
                setSelection(null);
                setMode((current) => current === "edit" ? "view" : "edit");
              }}
              style={{ height: 30, display: "flex", alignItems: "center", gap: 6, padding: "0 10px", border: "1px solid var(--color-border)", borderRadius: 5, background: mode === "view" ? "var(--color-bg-card)" : "transparent", color: "var(--color-text-secondary)", cursor: "pointer" }}
            >
              {mode === "edit" ? <Eye size={14} /> : <PencilLine size={14} />}
              <span className="type-caption" style={{ color: "inherit" }}>{mode === "edit" ? "View" : "Edit"}</span>
            </button>
            {onReviewCommit && (
              <button
                type="button"
                disabled={reviewCommitDisabled}
                title={hasUnsavedChanges ? "Save changes before review and commit" : !viewingCurrent ? "Return to the current version to review and commit" : "Open the review and commit workspace"}
                onClick={onReviewCommit}
                style={{ height: 30, display: "flex", alignItems: "center", gap: 6, padding: "0 12px", border: "none", borderRadius: 5, background: "var(--color-accent)", color: "var(--color-bg)", cursor: reviewCommitDisabled ? "not-allowed" : "pointer", opacity: reviewCommitDisabled ? 0.45 : 1 }}
              >
                <GitCommitHorizontal size={14} />
                <span className="type-caption" style={{ color: "inherit", fontWeight: 600 }}>{preparingCommit ? "Preparing…" : "Review & commit"}</span>
              </button>
            )}
          </div>
        </div>
        <div aria-label={`${artifactLabel} editor toolbar`} style={{ minHeight: 46, padding: "8px 12px", display: "flex", alignItems: "center", gap: 6, borderBottom: "1px solid var(--color-border)", background: "var(--color-bg-elevated)", overflowX: "auto" }}>
          <select aria-label="Document version" value={selectedRevision ?? ""} onChange={(event) => { setSelectedRevision(Number(event.target.value)); setSelection(null); }}
            style={{ height: 30, borderRadius: 5, border: "1px solid var(--color-border)", background: "var(--color-bg-card)", color: "var(--color-text)", padding: "0 8px", fontFamily: "var(--font-mono)", fontSize: 11 }}>
            {[...versions].sort((a, b) => b.revision - a.revision).map((item) => (
              <option key={item.revision} value={item.revision}>{item.status === "published" ? "Published" : item.revision === documentRevision ? "Current draft" : "Draft"} · v{versionNumberByRevision.get(item.revision) ?? 1}</option>
            ))}
          </select>
          <button type="button" onClick={async () => { if (await onSaveDocument(editorContent)) setSavedEditorContent(editorContent); }} disabled={mode === "view" || !viewingCurrent || saving || editorContent === savedEditorContent}
            style={{ height: 30, display: "flex", alignItems: "center", gap: 6, padding: "0 9px", border: "none", borderRadius: 5, background: "transparent", color: "var(--color-text-secondary)", cursor: "pointer", opacity: mode === "view" || !viewingCurrent || saving || editorContent === savedEditorContent ? 0.4 : 1 }}>
            <Save size={14} /> <span className="type-caption" style={{ color: "inherit" }}>{saving ? "Saving…" : "Save"}</span>
          </button>
          {onPublish && <button type="button" onClick={() => onPublish()} disabled={!viewingCurrent || saving || publishing || editorContent !== savedEditorContent || publishedRevision === documentRevision}
            title={!viewingCurrent ? "Historical versions are read-only" : editorContent !== savedEditorContent ? "Save changes before publishing" : "Publish this version"}
            style={{ height: 30, display: "flex", alignItems: "center", gap: 6, padding: "0 10px", border: "1px solid var(--color-accent)", borderRadius: 5, background: "var(--color-accent-dim)", color: "var(--color-accent)", cursor: "pointer", opacity: !viewingCurrent || saving || publishing || editorContent !== savedEditorContent || publishedRevision === documentRevision ? 0.45 : 1 }}>
            <CheckCircle2 size={14} /> <span className="type-caption" style={{ color: "inherit" }}>{!viewingCurrent ? versionStateLabel : publishedRevision === documentRevision ? "Published" : publishing ? "Publishing…" : "Publish"}</span>
          </button>}
          {mode === "edit" && <>
            {toolbarButton("Undo", <Undo2 size={14} />, () => editorRef.current?.undo(), !viewingCurrent)}
            {toolbarButton("Redo", <Redo2 size={14} />, () => editorRef.current?.redo(), !viewingCurrent)}
            <span style={{ width: 1, height: 22, background: "var(--color-border)", margin: "0 3px" }} />
            <select aria-label="Text style" defaultValue="normal" disabled={!viewingCurrent} onChange={(event) => { editorRef.current?.applyFormat(event.target.value as "normal" | "heading2" | "heading3"); event.currentTarget.value = "normal"; }}
              style={{ height: 30, borderRadius: 5, border: "1px solid var(--color-border)", background: "var(--color-bg-card)", color: "var(--color-text)", padding: "0 8px", fontSize: 11 }}>
              <option value="normal">Normal</option><option value="heading2">Heading 2</option><option value="heading3">Heading 3</option>
            </select>
            {toolbarButton("Bold", <Bold size={14} />, () => editorRef.current?.applyFormat("bold"), !viewingCurrent)}
            {toolbarButton("Italic", <Italic size={14} />, () => editorRef.current?.applyFormat("italic"), !viewingCurrent)}
            {toolbarButton("Bulleted list", <List size={14} />, () => editorRef.current?.applyFormat("bullet"), !viewingCurrent)}
            {toolbarButton("Numbered list", <ListOrdered size={14} />, () => editorRef.current?.applyFormat("numbered"), !viewingCurrent)}
            {toolbarButton("Link", <Link size={14} />, () => editorRef.current?.applyFormat("link"), !viewingCurrent)}
            {toolbarButton("Table", <Table2 size={14} />, () => editorRef.current?.applyFormat("table"), !viewingCurrent)}
          </>}
        </div>
        {mode === "view" ? (
          <div style={{ minHeight: 0, flex: 1 }}>
            <SpecPreview content={displayedDocument} />
          </div>
        ) : (
          <div data-document-scroll="true" style={{ minHeight: 0, flex: 1, overflow: "auto", background: "var(--color-bg)" }}>
            <div style={{ borderBottom: "1px solid var(--color-border-light)" }}>
              <SpecPreview content={header} scrollable={false} />
            </div>
            <SpecEditor key={viewingCurrent ? "current" : selectedRevision ?? "history"} ref={editorRef} content={displayedEditorContent} specType={artifactType} readOnly={!viewingCurrent}
              showLineNumbers={false} autoHeight onChange={viewingCurrent ? setEditorContent : () => undefined} onSelectionChange={viewingCurrent ? setSelection : undefined} />
          </div>
        )}
        {mode === "edit" && selection?.sectionTitle && onAddComment && (
          <div role="dialog" aria-label={`Comment on selected text in ${selection.sectionTitle}`} style={{ position: "absolute", right: 18, bottom: 18, width: 300, padding: 12, border: "1px solid rgba(0,212,170,.35)", borderRadius: 8, background: "var(--color-bg-card)", boxShadow: "0 12px 32px rgba(0,0,0,.45)", zIndex: 5 }}>
            <div className="type-compact-label">{selection.sectionTitle} · selected text</div>
            <div className="type-caption" style={{ marginTop: 6, paddingLeft: 8, borderLeft: "2px solid var(--color-accent)", color: "var(--color-text-secondary)", maxHeight: 48, overflow: "hidden" }}>“{selection.text}”</div>
            <textarea autoFocus aria-label="Comment on selected text" value={commentText} onChange={(event) => setCommentText(event.target.value)} placeholder="Describe the change you want…"
              style={{ width: "100%", minHeight: 72, marginTop: 10, padding: 9, borderRadius: 5, border: "1px solid var(--color-border)", background: "var(--color-bg-elevated)", color: "var(--color-text)", resize: "vertical" }} />
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 8 }}>
              <button type="button" className="type-badge" onClick={() => { setSelection(null); setCommentText(""); }} style={{ border: 0, background: "transparent", color: "var(--color-text-secondary)" }}>Cancel</button>
              <button type="button" className="type-badge" disabled={commentText.trim().length < 3} onClick={() => { onAddComment(selection.sectionTitle as string, commentText.trim(), { selected_text: selection.text, selection_start: selection.from, selection_end: selection.to, anchor_revision: revision ?? 0 }); setSelection(null); setCommentText(""); }}
                style={{ border: 0, borderRadius: 5, padding: "7px 12px", background: "var(--color-accent)", color: "var(--color-bg)" }}>Add comment</button>
            </div>
          </div>
        )}
      </section>
    );
  }

  return (
    <section
      className="surface guided-authoring-preview"
      aria-label={`Generated ${artifactLabel}, revision ${revision ?? "unknown"}`}
      style={{
        width: expanded ? "min(45vw, 680px)" : 420,
        flexShrink: expanded ? 1 : 0,
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
          {artifactLabel} · rev {revision ?? "-"}
        </span>
        {artifactPath && (
          <a
            className="type-caption"
            href={`/editor?path=${encodeURIComponent(artifactPath)}`}
            style={{ color: "var(--color-text-secondary)", textDecoration: "none" }}
          >
            Open full editor ↗
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
              {editingTitle === section.title ? (
                <div>
                  <div className="type-section-title" style={{ marginBottom: 8 }}>
                    {section.title}
                  </div>
                  <textarea
                    aria-label={`Edit ${section.title} draft content`}
                    value={editingBody}
                    disabled={saving}
                    onChange={(event) => setEditingBody(event.target.value)}
                    style={{
                      width: "100%",
                      minHeight: 180,
                      resize: "vertical",
                      padding: 12,
                      borderRadius: 6,
                      border: "1px solid var(--color-border)",
                      background: "var(--color-bg-elevated)",
                      color: "var(--color-text)",
                      fontFamily: "var(--font-mono)",
                      fontSize: 12,
                      lineHeight: 1.6,
                    }}
                  />
                  <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                    <button
                      type="button"
                      className="type-badge"
                      disabled={saving || editingBody.trim().length < 3}
                      onClick={async () => {
                        if (!onEditDraftSection) return;
                        const saved = await onEditDraftSection(section.title, editingBody);
                        if (saved) setEditingTitle(null);
                      }}
                      style={{
                        border: "none",
                        borderRadius: 5,
                        padding: "7px 12px",
                        background: "var(--color-accent)",
                        color: "var(--color-bg)",
                        cursor: "pointer",
                      }}
                    >
                      {saving ? "Saving…" : "Save section"}
                    </button>
                    <button
                      type="button"
                      className="type-badge"
                      disabled={saving}
                      onClick={() => setEditingTitle(null)}
                      style={{
                        border: "1px solid var(--color-border)",
                        borderRadius: 5,
                        padding: "7px 12px",
                        background: "transparent",
                        color: "var(--color-text-secondary)",
                        cursor: "pointer",
                      }}
                    >
                      Cancel
                    </button>
                  </div>
                  <div className="type-caption" style={{ marginTop: 8 }}>
                    Manual edits are preserved when linked answers change.
                  </div>
                </div>
              ) : (
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {`## ${section.title}\n\n${section.body}`}
                </ReactMarkdown>
              )}
              {editingTitle !== section.title && (
                <>
                  <SectionProvenance
                    section={section.provenance ?? {
                      title: section.title,
                      question_ids: [],
                      coverage_ids: [],
                      state: "generated",
                    }}
                    onEditDraft={() => {
                      if (!onEditDraftSection) return;
                      setEditingTitle(section.title);
                      setEditingBody(section.body.trim());
                    }}
                    onComment={onAddComment ? () => {
                      setCommentingTitle(section.title);
                      setCommentText("");
                    } : undefined}
                    hasComment={comments.some((item) => item.section_title === section.title)}
                  />
                  {commentingTitle === section.title && (
                    <div style={{ marginTop: 8 }}>
                      <textarea
                        autoFocus
                        aria-label={`Review comment for ${section.title}`}
                        value={commentText}
                        onChange={(event) => setCommentText(event.target.value)}
                        placeholder="Describe the change or content you want in this section…"
                        style={{
                          width: "100%",
                          minHeight: 84,
                          resize: "vertical",
                          padding: 10,
                          borderRadius: 6,
                          border: "1px solid var(--color-border)",
                          background: "var(--color-bg-elevated)",
                          color: "var(--color-text)",
                        }}
                      />
                      <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                        <button
                          type="button"
                          disabled={commentText.trim().length < 3}
                          onClick={() => {
                            onAddComment?.(section.title, commentText.trim());
                            setCommentingTitle(null);
                            setCommentText("");
                          }}
                          className="type-badge"
                          style={{ border: "none", borderRadius: 5, padding: "7px 12px", background: "var(--color-accent)", color: "var(--color-bg)" }}
                        >
                          Add to review
                        </button>
                        <button type="button" className="type-badge" onClick={() => setCommentingTitle(null)} style={{ border: "1px solid var(--color-border)", borderRadius: 5, padding: "7px 12px", background: "transparent", color: "var(--color-text-secondary)" }}>
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
