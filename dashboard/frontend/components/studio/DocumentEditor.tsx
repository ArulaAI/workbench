"use client";

import { useEffect, useRef, useState } from "react";
import { Download, Eye, Loader2, Pencil } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { SpecEditor, type SpecEditorHandle } from "@/components/editor/SpecEditor";
import { api } from "./api";
import { labels, type Snapshot } from "./types";

export function DocumentEditor({ featureId, snapshot, sectionTitle, currentVersion, busy, onSave, onClose }: {
  featureId: string; snapshot: Snapshot; sectionTitle?: string; currentVersion?: string | null; busy: boolean;
  onSave: (markdown: string) => Promise<boolean>; onClose: () => void;
}) {
  const [original, setOriginal] = useState<string | null>(null), [text, setText] = useState("");
  const [preview, setPreview] = useState(false), [discard, setDiscard] = useState(false);
  const [error, setError] = useState(""), [attempt, setAttempt] = useState(0), [saving, setSaving] = useState(false);
  const [recovered, setRecovered] = useState(false);
  const editor = useRef<SpecEditorHandle>(null), savingRef = useRef(false);
  const storageKey = `studio-markdown:${featureId}:${snapshot.kind}:${snapshot.id}`;
  const dirty = original !== null && text !== original;
  const waiting = busy || saving;

  useEffect(() => {
    const controller = new AbortController();
    setError("");
    api<{markdown: string}>(`/features/${featureId}/versions/${snapshot.id}/editable`, undefined, controller.signal).then(result => {
      let draft: string | null = null;
      try {draft = sessionStorage.getItem(storageKey);} catch { /* Storage may be unavailable. */ }
      setOriginal(result.markdown); setText(draft ?? result.markdown); setRecovered(draft !== null && draft !== result.markdown);
    }).catch(e => {if (e.name !== "AbortError") setError(e.message);});
    return () => controller.abort();
  }, [featureId, snapshot.id, storageKey, attempt]);

  useEffect(() => {
    if (original === null) return;
    try {if (dirty) sessionStorage.setItem(storageKey, text); else sessionStorage.removeItem(storageKey);} catch { /* Navigation warning still applies. */ }
  }, [dirty, original, storageKey, text]);

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {event.preventDefault(); event.returnValue = "";};
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  useEffect(() => {
    if (original !== null && sectionTitle && !preview) editor.current?.scrollToSection(sectionTitle);
  }, [original, sectionTitle, preview]);

  function close() {
    try {sessionStorage.removeItem(storageKey);} catch { /* No stored draft. */ }
    onClose();
  }

  async function save() {
    if (waiting || savingRef.current || original === null) return;
    if (!dirty) {close(); return;}
    savingRef.current = true; setSaving(true); setError("");
    try {
      if (await onSave(text)) close();
      else setError("Your changes have not been saved. Your text is still here. Check the message above, correct the draft or download it before leaving.");
    } catch (e) {setError((e as Error).message);}
    finally {savingRef.current = false; setSaving(false);}
  }

  function download() {
    const url = URL.createObjectURL(new Blob([text], {type: "text/markdown;charset=utf-8"}));
    const link = document.createElement("a"); link.href = url; link.download = `${snapshot.kind}-unsaved-draft.md`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return <div className="studio-full-editor" aria-label={`Edit ${labels[snapshot.kind]} document`}>
    <div className="studio-document-toolbar"><div className="studio-view-toggle" role="group" aria-label="Editor mode">
      <button aria-pressed={!preview} className={!preview ? "selected" : ""} onClick={() => setPreview(false)}><Pencil size={14} /> Edit</button>
      <button aria-pressed={preview} className={preview ? "selected" : ""} onClick={() => setPreview(true)} disabled={original === null}><Eye size={14} /> Preview</button>
    </div><div className="studio-toolbar-actions">
      <span className="studio-editor-status" role="status">{saving ? "Saving…" : dirty ? "Unsaved changes" : `Editing v${snapshot.number}`}</span>
      <button aria-label="Download draft" title="Download your current Markdown draft" disabled={original === null} onClick={download}><Download size={15} /></button>
      <button disabled={saving} onClick={() => dirty ? setDiscard(true) : close()}>Cancel editing</button>
      <button className="primary" disabled={waiting || original === null} onClick={() => void save()}>{saving && <Loader2 size={14} className="studio-spin" />}Save and view</button>
    </div></div>
    <div className="studio-editor-help"><p>Edit the whole {labels[snapshot.kind]} here. Save once to create a new version and return to the document.</p>
      <details><summary>Markdown tips</summary><p>Keep the existing section headings. Add a section with <code># Heading</code> or a subsection with <code>## Heading</code>. Keep existing row IDs; use <code>new</code> for a new row. Sources and publication records stay attached to the saved version.</p></details>
    </div>
    {recovered && <div className="studio-notice" role="status">Your unsaved Markdown draft was recovered in this tab.</div>}
    {currentVersion !== snapshot.id && <div className="studio-notice">A newer version is available. Saving will check for a conflict. Download your draft before leaving to review the latest document.</div>}
    {discard && <div className="studio-editor-discard" role="group" aria-label="Discard unsaved changes"><p>Discard your unsaved edits and return to the saved document?</p><button disabled={saving} onClick={() => setDiscard(false)}>Keep editing</button><button disabled={saving} onClick={close}>Discard changes</button></div>}
    {error && <div className="studio-editor-error" role="alert">{error}{original === null && <button onClick={() => setAttempt(value => value + 1)}>Retry loading editor</button>}</div>}
    {original === null ? <div className="studio-loading">{!error && <><Loader2 className="studio-spin" size={20} />Opening Markdown…</>}</div> : <>
      <div className="studio-markdown-input" hidden={preview} inert={waiting}>
        <SpecEditor ref={editor} content={text} specType={snapshot.kind} onChange={setText} ariaLabel="Document Markdown" />
      </div>
      {preview && <div className="studio-markdown-preview studio-prose"><p className="studio-muted">Preview of your unsaved draft</p><ReactMarkdown remarkPlugins={[remarkGfm]} disallowedElements={["img"]}>{text}</ReactMarkdown></div>}
    </>}
  </div>;
}
