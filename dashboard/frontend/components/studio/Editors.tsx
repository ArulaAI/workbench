"use client";

import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import type { Section } from "./types";

export function Dialog({ title, onClose, children, busy = false, descriptionId, role = "dialog", className = "" }: { title: string; onClose: () => void; children: React.ReactNode; busy?: boolean; descriptionId?: string; role?: "dialog" | "alertdialog"; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const busyRef = useRef(busy);
  busyRef.current = busy;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    (ref.current?.querySelector<HTMLElement>("textarea, input") || ref.current?.querySelector<HTMLElement>("button"))?.focus();
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busyRef.current) onClose();
      if (event.key !== "Tab") return;
      const focusable = ref.current?.querySelectorAll<HTMLElement>('button:not(:disabled), textarea:not(:disabled), input:not(:disabled), select:not(:disabled), [tabindex="0"]');
      if (!focusable?.length) {event.preventDefault(); ref.current?.focus(); return;}
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", handler);
    return () => { document.removeEventListener("keydown", handler); previous?.focus(); };
  }, [onClose]);
  return <div className="studio-overlay"><div ref={ref} tabIndex={-1} className={`studio-dialog surface ${className}`} role={role} aria-modal="true" aria-label={title} aria-describedby={descriptionId} aria-busy={busy}><header><h2>{title}</h2><button onClick={onClose} disabled={busy} aria-label="Close dialog"><X size={18} /></button></header>{children}</div></div>;
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
