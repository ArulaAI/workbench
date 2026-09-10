"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowRight, Loader2 } from "lucide-react";
import { api } from "./api";
import { GenerationSetup } from "./GenerationSetup";
import { intakeFor, labels, type Command, type Feature, type Kind } from "./types";

export function ExistingDocumentStart({features, kind, onOpen, onStarted, onNewDescription, onSavingChange}: {
  features: Feature[]; kind: "design" | "rfc";
  onOpen: (id: string, kind: Kind) => void;
  onStarted: (feature: Feature, kind: Kind) => void;
  onNewDescription: () => void;
  onSavingChange: (saving: boolean) => void;
}) {
  const [id, setId] = useState("");
  const [workspace, setWorkspace] = useState<Feature | null>(null);
  const [loading, setLoading] = useState(false), [saving, setSaving] = useState(false), [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const pending = useRef<{fingerprint: string; id: string} | null>(null);
  const inFlight = useRef(false);
  const candidates = features.filter(f => f.documents.prd.head || kind === "rfc" && f.documents.design.head);

  useEffect(() => {
    setWorkspace(null); setError(""); setLoading(Boolean(id));
    if (!id) return;
    const controller = new AbortController();
    api<Feature>(`/features/${id}`, undefined, controller.signal).then(value => {if (!controller.signal.aborted) setWorkspace(value);}).catch(e => {
      if (e.name !== "AbortError") setError(e.message);
    }).finally(() => {if (!controller.signal.aborted) setLoading(false);});
    return () => controller.abort();
  }, [id, refresh]);

  async function start(command: Command) {
    if (!workspace || inFlight.current) return false;
    inFlight.current = true; setSaving(true); onSavingChange(true); setError("");
    try {
      const fingerprint = JSON.stringify({workspace: workspace.id, command});
      if (pending.current?.fingerprint !== fingerprint) pending.current = {fingerprint, id:crypto.randomUUID()};
      const next = await api<Feature>(`/features/${workspace.id}/commands`, {...command, kind,
        expected_revision: workspace.revision, request_id:pending.current.id});
      pending.current = null;
      onStarted(next, kind);
      return true;
    } catch (e) {
      setError((e as Error).message);
      try {setWorkspace(await api<Feature>(`/features/${workspace.id}`));} catch {setWorkspace(null);}
      return false;
    } finally {inFlight.current = false; setSaving(false); onSavingChange(false);}
  }

  const existing = workspace && (workspace.documents[kind].head || intakeFor(workspace, kind));
  const active = workspace?.operations.find(o => o.status === "queued" || o.status === "running");
  return <div className="studio-existing-start">
    <p className="studio-muted">Choose the workspace with the documents you want to use. Your {labels[kind]} will stay in that workspace.</p>
    {candidates.length ? <>
      <label htmlFor="source-workspace">Workspace with source documents</label>
      <select id="source-workspace" value={id} disabled={saving} onChange={e => setId(e.target.value)}>
        <option value="">Select a workspace</option>
        {candidates.map(f => <option key={f.id} value={f.id}>{f.title}</option>)}
      </select>
    </> : <div className="studio-existing-empty"><p className="studio-muted">No saved {kind === "design" ? "PRDs" : "PRDs or Design specs"} yet. You can start from a new description.</p><button type="button" onClick={onNewDescription}>Use a new description <ArrowRight size={14} /></button></div>}
    {loading && <p className="studio-muted" role="status"><Loader2 className="studio-spin" size={14} /> Loading source documents…</p>}
    {error && <div><p className="studio-error-text" role="alert">{error}</p><button type="button" disabled={saving || loading} onClick={() => setRefresh(value => value + 1)}>Reload source documents</button></div>}
    {workspace && (existing ? <div className="studio-existing-empty">
      <p className="studio-muted">{workspace.documents[kind].head ? `This workspace already has a ${labels[kind]}. Open it to review or make changes.` : `A ${labels[kind]} is already in progress. Continue with its saved sources and answers.`}</p>
      <button type="button" className="primary" disabled={saving} onClick={() => onOpen(workspace.id, kind)}>{workspace.documents[kind].head ? `Open ${labels[kind]}` : `Continue ${labels[kind]}`} <ArrowRight size={14} /></button>
    </div> : active ? <div className="studio-existing-empty">
      <p className="studio-muted">This workspace is already generating a {labels[active.kind]}. Open it to check progress before starting another document.</p>
      <button type="button" onClick={() => onOpen(workspace.id, active.kind)}>Open workspace <ArrowRight size={14} /></button>
    </div> : <GenerationSetup key={`${workspace.id}-${kind}`} feature={workspace} kind={kind} busy={saving} onCommand={start} includeBrief={false} onOpenSource={sourceKind => onOpen(workspace.id, sourceKind)} />)}
  </div>;
}
