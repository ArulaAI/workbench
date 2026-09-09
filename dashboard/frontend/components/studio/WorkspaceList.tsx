"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowRight, History, Loader2, Trash2 } from "lucide-react";
import { api } from "./api";
import { Dialog } from "./Editors";
import { kinds, labels, type Feature, type Kind } from "./types";

export function WorkspaceList({ features, onOpen, onDeleted, onRefresh }: {
  features: Feature[];
  onOpen: (id: string, kind: Kind) => void;
  onDeleted: (id: string) => void;
  onRefresh: () => Promise<void>;
}) {
  const [target, setTarget] = useState<Feature | null>(null);
  const [deleting, setDeleting] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const inFlight = useRef(false), heading = useRef<HTMLHeadingElement>(null);
  const close = useCallback(() => setTarget(null), []);
  useEffect(() => {if (notice) heading.current?.focus();}, [notice]);

  async function remove() {
    if (!target || inFlight.current) return;
    inFlight.current = true; setDeleting(true); setError("");
    try {
      await api(`/features/${target.id}`, {expected_revision: target.revision}, undefined, "DELETE");
      onDeleted(target.id); setTarget(null); setNotice(`“${target.title}” was deleted.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The workspace could not be deleted. Try again.");
      // Keep the reviewed revision in the dialog. A conflict requires reopening it.
      await onRefresh().catch(() => {});
    } finally {
      inFlight.current = false; setDeleting(false);
    }
  }

  return <aside className="studio-recent">
    <h2 ref={heading} tabIndex={-1}>Your workspaces <span>{features.length}</span></h2>
    {notice && <p className="studio-workspace-notice" role="status">{notice}</p>}
    {features.length === 0 ? <div className="studio-empty-small"><History size={24} /><p>Your workspaces will appear here.<br />Come back to any draft, any time.</p></div> : features.map(f => <article className="studio-feature-card surface" key={f.id} aria-label={f.title}>
      <button className="studio-feature-open" onClick={() => onOpen(f.id, f.initial_kind || "prd")} aria-label={`Open workspace: ${f.title}`}>
        <strong>{f.title}</strong><p>{f.brief}</p>
        <div className="studio-feature-versions">{kinds.map(k => <span key={k} className={f.documents[k].published ? "published" : ""}>{labels[k]} {f.documents[k].head ? `v${f.documents[k].versions.length}` : "·"}</span>)}</div>
        <small>Open workspace <ArrowRight size={12} /></small>
      </button>
      <button className="studio-feature-delete" aria-label={`Delete workspace: ${f.title}`} title="Delete workspace" onClick={() => {setError(""); setNotice(""); setTarget(f);}}><Trash2 size={16} /></button>
    </article>)}
    {target && <Dialog title="Delete workspace?" role="alertdialog" descriptionId="delete-workspace-description" className="studio-delete-dialog" busy={deleting} onClose={close}>
      <div className="studio-dialog-body">
        <p className="studio-delete-title">{target.title}</p>
        <p id="delete-workspace-description" className="studio-muted">This permanently deletes the workspace, including its PRD, Design spec, RFC, all versions, chat, and comments. Any generation in progress will be discarded. This cannot be undone.</p>
        {error && <p className="studio-error-text" role="alert">{error}</p>}
      </div>
      <footer><button onClick={close} disabled={deleting}>Cancel</button><button className="studio-danger" onClick={() => void remove()} disabled={deleting}>{deleting ? <Loader2 size={14} className="studio-spin" /> : <Trash2 size={14} />}{deleting ? "Deleting…" : "Delete workspace"}</button></footer>
    </Dialog>}
  </aside>;
}
