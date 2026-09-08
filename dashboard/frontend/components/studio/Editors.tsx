"use client";

import { useEffect, useRef, useState } from "react";
import { Plus, Trash2, X } from "lucide-react";
import type { Item, Section } from "./types";

function Dialog({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    (ref.current?.querySelector<HTMLElement>("textarea, input") || ref.current?.querySelector<HTMLElement>("button"))?.focus();
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key !== "Tab") return;
      const focusable = ref.current?.querySelectorAll<HTMLElement>('button:not(:disabled), textarea:not(:disabled), input:not(:disabled), select:not(:disabled), [tabindex="0"]');
      if (!focusable?.length) return;
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", handler);
    return () => { document.removeEventListener("keydown", handler); previous?.focus(); };
  }, [onClose]);
  return <div className="studio-overlay"><div ref={ref} className="studio-dialog surface" role="dialog" aria-modal="true" aria-label={title}><header><h2>{title}</h2><button onClick={onClose} aria-label="Close dialog"><X size={18} /></button></header>{children}</div></div>;
}

export function SectionEditor({ section, onClose, onSave }: { section: Section; onClose: () => void; onSave: (body: string, items: Item[]) => Promise<boolean> }) {
  const [body, setBody] = useState(section.body), [items, setItems] = useState(section.items);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  function update(index: number, patch: Partial<Item>) { setItems(items.map((item, i) => i === index ? {...item, ...patch} : item)); }
  return <Dialog title={`Edit ${section.title}`} onClose={onClose}><form onSubmit={async e => {
    e.preventDefault(); setSaving(true); setError("");
    if (await onSave(body, items)) onClose();
    else setError("Your text is still here. If this section changed elsewhere, close and reopen it after copying your edits.");
    setSaving(false);
  }}><div className="studio-dialog-body">
    <p className="studio-muted">Saving creates a new version and protects this section from whole-document AI revisions. A targeted chat request can still revise it.</p>
    <label htmlFor="section-body">Section text · Markdown supported</label><textarea id="section-body" rows={12} value={body} onChange={e => setBody(e.target.value)} />
    {(items.length > 0 || ["stories", "requirements", "guardrails", "success"].includes(section.id)) && <div className="studio-item-editor"><h3>Structured entries</h3>{items.map((item, index) => <fieldset key={item.id}><legend>{item.id.startsWith("new-") ? "New entry" : item.id}</legend><div className="studio-row"><label htmlFor={`statement-${index}`}>Statement</label><button type="button" onClick={() => setItems(items.filter((_, i) => i !== index))} aria-label={`Remove ${item.id}`}><Trash2 size={14} /></button></div><textarea id={`statement-${index}`} required rows={3} value={item.statement} onChange={e => update(index, {statement: e.target.value})} />
      <label htmlFor={`verification-${index}`}>Verification or outcome</label><textarea id={`verification-${index}`} required rows={3} value={item.verification} onChange={e => update(index, {verification: e.target.value})} />
      <label htmlFor={`references-${index}`}>Related IDs · comma separated</label><input id={`references-${index}`} value={item.references.join(", ")} onChange={e => update(index, {references: e.target.value.split(",").map(v => v.trim()).filter(Boolean)})} />
    </fieldset>)}<button type="button" onClick={() => setItems([...items, {id: `new-${crypto.randomUUID()}`, statement: "", verification: "", references: []}])}><Plus size={14} /> Add entry</button></div>}
    {error && <p role="alert" className="studio-error-text">{error}</p>}
  </div><footer><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={saving} type="submit">{saving ? "Saving…" : "Save new version"}</button></footer></form></Dialog>;
}

export function CommentEditor({ section, quote, onClose, onSave }: { section: Section; quote: string; onClose: () => void; onSave: (text: string, blocking: boolean) => Promise<boolean> }) {
  const [text, setText] = useState(""), [blocking, setBlocking] = useState(false), [saving, setSaving] = useState(false);
  return <Dialog title={`Comment on ${section.title}`} onClose={onClose}><form onSubmit={async e => {e.preventDefault(); setSaving(true); if (await onSave(text, blocking)) onClose(); setSaving(false);}}><div className="studio-dialog-body">
    {quote && <blockquote>{quote}</blockquote>}
    <label htmlFor="review-comment">Your feedback</label><textarea id="review-comment" rows={6} required value={text} onChange={e => setText(e.target.value)} placeholder="What needs to change, and why?" />
    <label className="studio-checkbox"><input type="checkbox" checked={blocking} onChange={e => setBlocking(e.target.checked)} /> Resolve this before publishing</label>
    <p className="studio-muted">The comment stays linked to this section and version. You decide when it is resolved.</p>
  </div><footer><button type="button" onClick={onClose}>Cancel</button><button type="submit" className="primary" disabled={!text.trim() || saving}>{saving ? "Saving…" : "Add comment"}</button></footer></form></Dialog>;
}
