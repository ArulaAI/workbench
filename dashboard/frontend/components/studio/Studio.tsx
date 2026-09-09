"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowLeft, ArrowRight, Check, ChevronDown, Download, FileText, GitCompareArrows, History, Layers, Loader2, MessageSquare, Plus, Send, Sparkles, X } from "lucide-react";
import { IconRail } from "@/components/landing/IconRail";
import { api, studioUrl } from "./api";
import { DocumentCanvas, VersionComparison } from "./Document";
import { CommentEditor, SectionEditor } from "./Editors";
import { ClarificationFlow } from "./Clarification";
import { GenerationSetup } from "./GenerationSetup";
import { intakeFor, kinds, labels, type Command, type Feature, type Kind, type Section, type Snapshot } from "./types";
import "./studio.css";

const EXAMPLE = "Let product managers save their current Define filters as a named personal view, switch between saved views, and rename or delete one. Views should survive a browser restart. Keep sharing out of the first release and preserve the existing default view.";

export default function Studio() {
  const [features, setFeatures] = useState<Feature[]>([]), [feature, setFeature] = useState<Feature | null>(null);
  const [selected, setSelected] = useState<string | null>(null), [kind, setKind] = useState<Kind>("prd");
  const [connected, setConnected] = useState(false), [error, setError] = useState(""), [saving, setSaving] = useState(false);
  const [listOpen, setListOpen] = useState(false), [panel, setPanel] = useState<"outline" | "review">("outline");
  const [startKind, setStartKind] = useState<Kind>("prd");
  const [title, setTitle] = useState(""), [brief, setBrief] = useState(""), [context, setContext] = useState("");
  const [message, setMessage] = useState(""), [scope, setScope] = useState("");
  const [viewId, setViewId] = useState(""), [historical, setHistorical] = useState<Snapshot | null>(null);
  const [compare, setCompare] = useState(false), [before, setBefore] = useState<Snapshot | null>(null);
  const [compareError, setCompareError] = useState("");
  const [edit, setEdit] = useState<{section: Section; version: string} | null>(null);
  const [comment, setComment] = useState<{section: Section; quote: string; version: string} | null>(null);
  const [notice, setNotice] = useState(""), [dismiss, setDismiss] = useState(""), [dismissReason, setDismissReason] = useState("");
  const composer = useRef<HTMLTextAreaElement>(null), conversation = useRef<HTMLDivElement>(null);
  const canvasScroll = useRef<HTMLDivElement>(null);
  const pendingCommand = useRef<{fingerprint: string; id: string} | null>(null);
  const pendingCreate = useRef<{fingerprint: string; id: string} | null>(null);
  const active = feature?.operations.find(o => o.status === "queued" || o.status === "running");
  const generating = Boolean(active);
  const busy = saving || generating;
  const doc = feature?.documents[kind];
  const snapshot = viewId ? historical : doc?.snapshot;
  const isHistorical = Boolean(viewId && viewId !== doc?.head);
  const lastOperation = feature?.operations.filter(o => o.kind === kind).at(-1);
  const failed = lastOperation && ["failed", "interrupted", "cancelled"].includes(lastOperation.status) ? lastOperation : null;
  const currentQuestion = doc?.snapshot?.questions.find(q => q.blocking) || doc?.snapshot?.questions[0];
  const comments = feature?.comments.filter(c => c.kind === kind) || [];
  const messages = feature?.messages.filter(m => m.kind === kind) || [];
  const intake = feature ? intakeFor(feature, kind) : undefined;
  const needsIntake = Boolean(intake && !doc?.head);

  const loadList = useCallback(async () => {
    const [health, result] = await Promise.all([api<{contract: number}>("/health"), api<Feature[]>("/features")]);
    if (health.contract !== 1) throw new Error("This preview is connected to an incompatible backend. Start the studio launcher.");
    setConnected(true); setFeatures(result);
  }, []);

  useEffect(() => {
    const query = new URLSearchParams(window.location.search), id = query.get("feature"), stage = query.get("document");
    if (id) setSelected(id);
    if (stage && kinds.includes(stage as Kind)) setKind(stage as Kind);
    loadList().catch(e => {setConnected(false); setError(e.message);});
  }, [loadList]);

  useEffect(() => {
    if (!selected) return;
    const controller = new AbortController();
    const load = () => api<Feature>(`/features/${selected}`, undefined, controller.signal).then(value => {
      setConnected(true);
      if (!new URLSearchParams(window.location.search).get("document")) setKind(value.initial_kind || "prd");
      setFeature(old => !old || old.id !== value.id || value.revision >= old.revision ? value : old);
    }).catch(e => { if (e.name !== "AbortError") {setConnected(false); setError(e.message);} });
    void load();
    const interval = setInterval(load, generating ? 1500 : 5000);
    return () => {controller.abort(); clearInterval(interval);};
  }, [selected, generating]);

  useEffect(() => {
    conversation.current?.scrollTo({top: conversation.current.scrollHeight, behavior: "smooth"});
  }, [messages.length, active?.id]);

  useEffect(() => {
    canvasScroll.current?.scrollTo({top:0});
  }, [selected, kind, viewId, compare]);

  useEffect(() => {
    if (!selected || !viewId) {setHistorical(null); return;}
    const controller = new AbortController(); setHistorical(null);
    api<Snapshot>(`/features/${selected}/versions/${viewId}`, undefined, controller.signal).then(setHistorical).catch(e => {if (e.name !== "AbortError") setError(e.message);});
    return () => controller.abort();
  }, [selected, viewId]);

  useEffect(() => {
    setBefore(null); setCompareError("");
    if (!compare || !selected || !snapshot?.parent_id) return;
    const controller = new AbortController();
    api<Snapshot>(`/features/${selected}/versions/${snapshot.parent_id}`, undefined, controller.signal).then(setBefore).catch(e => {if (e.name !== "AbortError") setCompareError(e.message);});
    return () => controller.abort();
  }, [compare, selected, snapshot?.id, snapshot?.parent_id]);

  function choose(id: string | null, stage: Kind = "prd") {
    setSelected(id); setFeature(null); setKind(stage); setScope(""); setMessage(""); setViewId(""); setCompare(false); setListOpen(false); setNotice(""); setError("");
    window.history.replaceState(null, "", id ? `?feature=${id}&document=${stage}` : window.location.pathname);
    void loadList().catch(e => setError(e.message));
  }
  function switchKind(stage: Kind) {
    setKind(stage); setScope(""); setMessage(""); setViewId(""); setCompare(false); setNotice("");
    window.history.replaceState(null, "", `?feature=${selected}&document=${stage}`);
  }
  const closeEdit = useCallback(() => setEdit(null), []), closeComment = useCallback(() => setComment(null), []);

  async function command(payload: Command): Promise<boolean> {
    if (!feature) return false;
    setSaving(true); setError(""); setNotice("");
    try {
      const fingerprint = JSON.stringify({feature:feature.id, kind, payload});
      if (pendingCommand.current?.fingerprint !== fingerprint) pendingCommand.current = {fingerprint, id:crypto.randomUUID()};
      const next = await api<Feature>(`/features/${feature.id}/commands`, {...payload, kind: payload.kind || kind, expected_revision: feature.revision, request_id: pendingCommand.current.id});
      pendingCommand.current = null;
      setFeature(old => !old || old.id === next.id && next.revision >= old.revision ? next : old); setConnected(true);
      if (payload.action === "publish") setNotice(`${labels[kind]} v${doc?.snapshot?.number} published. Downstream drafts will use this snapshot.`);
      if (["edit", "review_section", "restore", "reconcile", "revise"].includes(payload.action)) {setViewId(""); setCompare(false);}
      void loadList().catch(() => {});
      return true;
    } catch (e) {
      setError((e as Error).message);
      try {setFeature(await api<Feature>(`/features/${feature.id}`));} catch {setConnected(false);}
      return false;
    } finally {setSaving(false);}
  }

  async function create() {
    setSaving(true); setError("");
    try {
      const data = {title:title.trim(), brief:brief.trim(), context:context.trim(), kind:startKind};
      const fingerprint = JSON.stringify(data);
      if (pendingCreate.current?.fingerprint !== fingerprint) pendingCreate.current = {fingerprint, id:crypto.randomUUID()};
      const next = await api<Feature>("/features", {...data, request_id: pendingCreate.current.id});
      pendingCreate.current = null;
      choose(next.id, next.initial_kind || startKind); setFeature(next); setTitle(""); setBrief(""); setContext("");
    } catch (e) {setError((e as Error).message);} finally {setSaving(false);}
  }

  return <div className="studio-app"><IconRail /><div className="studio-shell">
    <header className="studio-topbar"><div className="studio-brand"><Link href="/define" aria-label="Back to Define"><ArrowLeft size={16} /></Link><span>Define</span><span className="studio-slash">/</span><strong>Authoring studio</strong><span className="studio-pill">Preview</span></div>
      <div className="studio-top-actions"><span className={`studio-connection ${connected ? "online" : ""}`} role="status"><i />{connected ? "Workspace connected" : "Connecting to workspace"}</span><button onClick={() => choose(null)}><Plus size={14} /> New feature</button></div></header>
    {error && <div className="studio-global-error" role="alert"><span>{error}</span><button onClick={() => {setError(""); void loadList().catch(e => setError(e.message));}}>Retry connection</button><button aria-label="Dismiss error" onClick={() => setError("")}><X size={16} /></button></div>}
    {notice && <div className="studio-success" role="status"><Check size={16} />{notice}<button aria-label="Dismiss notice" onClick={() => setNotice("")}><X size={14} /></button></div>}
    {!selected ? <main className="studio-start">
      <div className="studio-start-main"><div className="studio-eyebrow"><Layers size={16} /> GUIDED AUTHORING</div><h1>Start with the feature.<br /><span>Shape it together.</span></h1><p className="studio-intro">Start with a PRD, Design spec or RFC. Describe what you need, refine it together, and create the other documents when they help.</p>
        <form className="studio-brief surface" onSubmit={e => {e.preventDefault(); void create();}}><fieldset className="studio-document-choice" disabled={saving}><legend>What would you like to create?</legend>{kinds.map(k => <label className={`surface ${startKind === k ? "selected" : ""}`} key={k}><input type="radio" name="starting-document" checked={startKind === k} onChange={() => setStartKind(k)} /><span><strong>{labels[k]}</strong><small>{k === "prd" ? "Define the product direction" : k === "design" ? "Shape the user experience" : "Propose the engineering approach"}</small></span></label>)}</fieldset><label htmlFor="feature-title">Feature name</label><input id="feature-title" maxLength={160} required value={title} onChange={e => setTitle(e.target.value)} placeholder="e.g. Saved views for Define" />
          <label htmlFor="feature-brief">What should people be able to do?</label><textarea id="feature-brief" minLength={12} maxLength={20000} required rows={5} value={brief} onChange={e => setBrief(e.target.value)} placeholder="Who is it for? What changes for them? Include anything that should stay out of scope." />
          <details><summary>Have research, constraints or decisions? Add context <Plus size={12} /></summary><label htmlFor="feature-context" className="sr-only">Supporting context</label><textarea id="feature-context" maxLength={20000} rows={5} value={context} onChange={e => setContext(e.target.value)} placeholder="Paste supporting notes. We'll distinguish your evidence from proposed assumptions." /></details>
          <div className="studio-brief-footer"><button type="button" onClick={() => {setTitle("Saved views for Define"); setBrief(EXAMPLE);}}>Use an example</button><button className="primary" type="submit" disabled={saving || !connected || !title.trim() || brief.trim().length < 12}>{saving ? <Loader2 className="studio-spin" size={16} /> : <ArrowRight size={16} />} Continue with brief</button></div></form>
        <p className="studio-start-note">We’ll clarify any missing decisions, then generate your {labels[startKind]}. You can start with any document; the others are optional.</p>
      </div><aside className="studio-recent"><h2>Your feature workspaces <span>{features.length}</span></h2>{features.length === 0 ? <div className="studio-empty-small"><History size={24} /><p>Your features will appear here.<br />Come back to any draft, any time.</p></div> : features.map(f => <button className="studio-feature-card surface" key={f.id} onClick={() => choose(f.id, f.initial_kind || "prd")}><strong>{f.title}</strong><p>{f.brief}</p><div>{kinds.map(k => <span key={k} className={f.documents[k].published ? "published" : ""}>{labels[k]} {f.documents[k].head ? `v${f.documents[k].versions.length}` : "·"}</span>)}</div><small>Open workspace <ArrowRight size={12} /></small></button>)}</aside>
    </main> : !feature ? <div className="studio-loading"><Loader2 className="studio-spin" size={24} /><p>Opening your feature workspace…</p></div> : <>
      <div className="studio-feature-header"><div className="studio-feature-picker"><button aria-expanded={listOpen} onClick={() => setListOpen(!listOpen)}><h1>{feature.title}</h1><ChevronDown size={16} /></button>{listOpen && <div className="studio-feature-menu surface">{features.map(f => <button key={f.id} onClick={() => choose(f.id, f.initial_kind || "prd")}>{f.title}{f.id === feature.id && <Check size={14} />}</button>)}<button onClick={() => choose(null)}><Plus size={14} /> New feature</button></div>}<p>One feature. Connected documents. A clear history of decisions.</p></div>
        <div className="studio-stage-tabs" role="tablist" aria-label="Feature documents">{kinds.map(stage => {const d = feature.documents[stage]; return <button key={stage} role="tab" aria-selected={kind === stage} disabled={needsIntake && stage !== kind} onClick={() => switchKind(stage)}><span className="studio-stage-number">{d.published ? <Check size={12} /> : <FileText size={12} />}</span><span>{labels[stage]}<small>{needsIntake && stage === kind ? intake?.status === "ready" ? "Preparing draft" : "Clarifying brief" : d.stale.length ? "Upstream changed" : d.head ? `v${d.versions.length} · ${d.head === d.published ? "Published" : "Draft"}` : intakeFor(feature, stage) ? "Clarification started" : "Optional"}</small></span></button>;})}</div>
      </div>
      {needsIntake ? <ClarificationFlow key={`${feature.id}-${kind}`} feature={feature} kind={kind} active={active?.kind === kind ? active : undefined} failed={failed} busy={busy} saving={saving} onCommand={command} /> : <>
      <nav className="studio-mobile-nav" aria-label="Workspace panels"><a href="#studio-conversation">Conversation</a><a href="#studio-document">Document</a><a href="#studio-review" onClick={() => setPanel("review")}>Review</a></nav>
      <div className="studio-workspace"><aside className="studio-chat" id="studio-conversation"><div className="studio-panel-heading"><span><Sparkles size={15} /> Your writing partner</span><span className="studio-pill">{labels[kind]}</span></div>
        <div className="studio-conversation" ref={conversation} aria-live="polite" aria-relevant="additions">
          {messages.length === 0 && <div className="studio-chat-intro"><p>{kind === "design" ? "Translate the agreed product direction into a usable experience." : "Turn product intent into an engineering decision your team can review."}</p><p>Your brief and selected sources provide the foundation. Add constraints or refine a particular section as you go.</p></div>}
          {messages.map(m => <div className={`studio-message ${m.role}`} key={m.id}><div className="studio-message-author">{m.role === "user" ? "You" : "Workbench"}{m.section_id && <span> · {m.section_id}</span>}</div><p>{m.text}</p>{m.version_id && <button onClick={() => {setViewId(m.version_id === doc?.head ? "" : m.version_id!); setCompare(true);}}><GitCompareArrows size={12} /> Review changes</button>}</div>)}
          {active && <div className="studio-generating" role="status"><Loader2 className="studio-spin" size={16} /><div><strong>Writing {labels[active.kind]}…</strong><p>Your request is saved. You can leave and return.</p><button disabled={saving} onClick={() => void command({action: "cancel"})}>Cancel generation</button></div></div>}
          {failed && <div className="studio-generation-error"><strong>{failed.status === "cancelled" ? "Generation cancelled" : "Draft generation needs attention"}</strong><p>{failed.error}</p><button disabled={busy} onClick={() => void command({action: "retry"})}>Retry saved request</button></div>}
          {!busy && currentQuestion && <div className="studio-question surface"><div><span className="studio-pill amber">{doc?.publication_review?.find(r => r.id === "open_questions")?.acknowledgement?.disposition === "deferred" ? "Acknowledged · still open" : currentQuestion.blocking ? "Decision needed" : "Worth clarifying"}</span><small>1 of {doc?.snapshot?.questions.length}</small></div><h3>{currentQuestion.question}</h3><p>{currentQuestion.why}</p><button onClick={() => {setScope(""); setMessage(`Regarding “${currentQuestion.question}”: `); composer.current?.focus();}}>Answer in chat <ArrowRight size={14} /></button></div>}
        </div>
        <form className="studio-composer" onSubmit={async e => {e.preventDefault(); if (await command({action: "revise", text: message, ...(scope ? {section_id: scope} : {})})) setMessage("");}}>
          <label htmlFor="revision-scope">Revise</label><select id="revision-scope" value={scope} onChange={e => setScope(e.target.value)} disabled={!doc?.head || busy}><option value="">Whole document</option>{doc?.snapshot?.sections.map(s => <option value={s.id} key={s.id}>{s.title}</option>)}</select>
          <label className="sr-only" htmlFor="revision-request">Revision request</label><textarea ref={composer} id="revision-request" value={message} onChange={e => setMessage(e.target.value)} rows={4} placeholder={doc?.head ? "Ask for a change, answer a question, or add more context…" : `Generate the ${labels[kind]} to start refining it.`} disabled={!doc?.head || busy} />
          <div><small>{scope ? "Only this section will change" : "Direct edits stay protected"}</small><button type="submit" className="primary" aria-label="Send revision request" disabled={!message.trim() || !doc?.head || busy}><Send size={15} /></button></div>
        </form>
      </aside>
      <main className="studio-canvas" id="studio-document"><div className="studio-document-toolbar"><div className="studio-view-toggle"><button className={!compare ? "selected" : ""} onClick={() => setCompare(false)}><FileText size={14} /> Document</button><button className={compare ? "selected" : ""} onClick={() => setCompare(true)} disabled={!snapshot}><GitCompareArrows size={14} /> Changes</button></div><div className="studio-toolbar-actions">
        <label className="sr-only" htmlFor="version-history">Version history</label><History size={14} /><select id="version-history" value={viewId} onChange={e => setViewId(e.target.value)}><option value="">Current{doc?.snapshot ? ` · v${doc.snapshot.number}` : " draft"}</option>{doc?.versions.slice().reverse().filter(v => v.id !== doc.head).map(v => <option key={v.id} value={v.id}>v{v.number} · {v.summary.slice(0, 45)}</option>)}</select>
        {snapshot && <a title="Download this version as Markdown" aria-label="Download Markdown" href={`${studioUrl}/features/${feature.id}/versions/${snapshot.id}/markdown`}><Download size={16} /></a>}
        <button className={panel === "review" ? "selected" : ""} onClick={() => setPanel(panel === "review" ? "outline" : "review")}><MessageSquare size={14} /><span>Review</span>{comments.filter(c => ["open", "addressed"].includes(c.status)).length || ""}</button>
        {doc?.head && !isHistorical && (doc.blockers.length ? <button aria-label="Review publication blockers" onClick={() => {setPanel("outline"); requestAnimationFrame(() => document.getElementById("studio-publication")?.scrollIntoView({block:"nearest"}));}}>Review {doc.blockers.length}</button> : <button className="primary" aria-label="Publish current snapshot" title="Publish this exact version for downstream documents" disabled={busy || doc.published === doc.head} onClick={() => void command({action: "publish", version_id: doc.head!})}>{doc.published === doc.head ? <Check size={14} /> : "Publish"}</button>)}
      </div></div>
      <div className="studio-document-scroll" ref={canvasScroll}>
        {doc && doc.stale.length > 0 && <div className="studio-upstream-notice"><div><strong>{doc.stale.map(k => labels[k]).join(" and ")} changed</strong><p>This draft still uses its original published sources. Reconcile to create a version using the latest decisions.</p></div><button disabled={busy} onClick={() => void command({action: "reconcile"})}>Reconcile changes <ArrowRight size={14} /></button></div>}
        {isHistorical && <div className="studio-notice">Viewing saved v{historical?.number}. Comments stay anchored to this version.<button disabled={busy} onClick={() => void command({action: "restore", version_id: viewId})}>Restore as a new version</button><button onClick={() => setViewId("")}>Back to current</button></div>}
        {snapshot ? compare ? compareError ? <div className="studio-loading"><p>{compareError}</p><button onClick={() => setCompare(false)}>Return to document</button></div> : snapshot.parent_id && !before ? <div className="studio-loading">Loading comparison…</div> : <VersionComparison before={before} after={snapshot} versionLabels={Object.fromEntries(kinds.flatMap(k => feature.documents[k].versions.map(v => [v.id, `${labels[k]} v${v.number}`])))} /> : <DocumentCanvas snapshot={snapshot} historical={isHistorical} busy={busy} onEdit={s => setEdit({section: s, version: snapshot.id})} onComment={(s, quote) => setComment({section: s, quote, version: snapshot.id})} onScope={id => {setScope(id); composer.current?.focus();}} onReview={id => void command({action: "review_section", section_id: id, version_id: snapshot.id})} publicationReviews={doc?.publication_review} published={doc?.published === snapshot.id} onAcknowledge={command} /> : viewId ? <div className="studio-loading"><Loader2 className="studio-spin" size={20} />Loading version…</div> : <div className="studio-document-empty"><div className="studio-empty-icon"><FileText size={28} /></div><h2>{active?.kind === kind ? `Your first ${labels[kind]} is taking shape` : `Build your ${labels[kind]}`}</h2><p>{active?.kind === kind ? "We’re turning the brief into a structured draft, with assumptions and open decisions clearly marked." : "Choose the context for this document. You can create it directly from your brief or use selected published documents."}</p>
          {active?.kind === kind ? <div className="studio-draft-skeleton"><i /><i /><i /><i /></div> : <GenerationSetup key={`${feature.id}-${kind}`} feature={feature} kind={kind} busy={busy} onCommand={command} />}
        </div>}
      </div>
      </main>
      <aside className="studio-inspector" id="studio-review"><div className="studio-panel-heading"><span>{panel === "review" ? "Review comments" : "In this document"}</span>{panel === "review" && <button onClick={() => setPanel("outline")} aria-label="Close review panel"><X size={14} /></button>}</div>
        <div className="studio-inspector-scroll">{panel === "review" ? <>
          <p className="studio-muted">Select text or use a section’s comment button. Addressing feedback creates a version; resolving it is your decision.</p>
          {comments.length === 0 && <div className="studio-empty-small"><MessageSquare size={24} /><p>No comments yet.</p></div>}
          {comments.map(c => <article className="studio-comment surface" key={c.id}><a href={`#section-${c.section_id}`}>{doc?.snapshot?.sections.find(s => s.id === c.section_id)?.title || c.section_id}</a><div><span className="studio-pill">{c.status}</span>{c.blocking && <span className="studio-pill amber">Blocking</span>}</div>{c.outdated && <small className="studio-error-text">Quoted text has changed. Review the current section.</small>}{c.quote && <blockquote>{c.quote}</blockquote>}<p>{c.text}</p><button onClick={() => setViewId(c.version_id === doc?.head ? "" : c.version_id)}>View commented version</button>
            {c.addressed_version && <button onClick={() => {setViewId(c.addressed_version === doc?.head ? "" : c.addressed_version!); setCompare(true);}}>Review addressing revision</button>}
            <div className="studio-comment-actions">{["open", "addressed"].includes(c.status) ? <><button disabled={busy || c.outdated} onClick={() => void command({action: "revise", comment_id: c.id})}><Sparkles size={12} /> Address</button><button disabled={busy} onClick={() => void command({action: "resolve", comment_id: c.id})}>Resolve</button><button disabled={busy} onClick={() => {setDismiss(c.id); setDismissReason("");}}>Dismiss</button></> : <button disabled={busy} onClick={() => void command({action: "reopen", comment_id: c.id})}>Reopen</button>}</div>
            {dismiss === c.id && <form onSubmit={async e => {e.preventDefault(); if (await command({action: "dismiss", comment_id: c.id, text: dismissReason})) setDismiss("");}}><label htmlFor={`dismiss-${c.id}`}>Reason for dismissal</label><textarea id={`dismiss-${c.id}`} rows={3} required value={dismissReason} onChange={e => setDismissReason(e.target.value)} /><button type="submit" disabled={busy || !dismissReason.trim()}>Save dismissal</button></form>}
            {c.dispositions.at(-1)?.reason && <small>Decision: {c.dispositions.at(-1)?.reason}</small>}
          </article>)}
        </> : <><nav className="studio-outline" aria-label="Document sections">{snapshot?.sections.map((s, i) => <a key={s.id} href={`#section-${s.id}`}><span>{String(i + 1).padStart(2, "0")}</span>{s.title}{s.needs_review && <i title="Review needed" />}</a>)}{snapshot?.assumptions.length ? <a href="#section-assumptions">Proposed assumptions</a> : null}{snapshot && (snapshot.questions.length > 0 || !isHistorical && doc?.publication_review?.length) ? <a href="#section-open-decisions">Open questions review</a> : null}{snapshot?.coverage.length ? <a href="#section-rfc-coverage">RFC coverage</a> : null}{snapshot && <a href="#section-sources">Sources and provenance</a>}</nav>
          {snapshot && Object.keys(snapshot.pins).length === 0 && <div className="studio-source-pins"><h3>Built from</h3><p className="studio-muted">Brief, supporting context and saved answers.</p></div>}
          {snapshot && Object.keys(snapshot.pins).length > 0 && <div className="studio-source-pins"><h3>Built from</h3>{Object.entries(snapshot.pins).map(([k, id]) => <button key={k} onClick={() => {switchKind(k as Kind); setViewId(feature.documents[k as Kind].head === id ? "" : id!);}}><FileText size={13} /> {labels[k as Kind]} v{feature.documents[k as Kind].versions.find(v => v.id === id)?.number}<span>Published</span></button>)}</div>}
          <div className="studio-publish" id="studio-publication"><h3>{doc?.published === doc?.head && doc?.head ? "Snapshot published" : "Ready to share the direction?"}</h3><p>{doc?.published === doc?.head && doc?.head ? "Downstream documents can use this exact version." : "Publish a stable version for the next document. You can keep refining afterwards."}</p>
            {doc?.head && !isHistorical && doc.publication_review && <div className="studio-publication-checklist"><p>Your acknowledgements apply to this version. Changes require a fresh review.</p>{doc.publication_review.map(review => <a key={review.id} href={`#publication-review-${review.id}`} onClick={() => setCompare(false)}><span>{review.title}</span><span>{review.acknowledgement ? review.acknowledgement.disposition === "deferred" ? "Open · acknowledged" : "Confirmed" : review.legacy_published ? "Previously published" : "Review required"}</span></a>)}</div>}
            {doc?.head && !isHistorical && doc.blockers.length > 0 && <details open><summary>{doc.blockers.length} item{doc.blockers.length !== 1 ? "s" : ""} to review before publishing</summary><ul>{doc.blockers.map((b, i) => <li key={i}>{b}</li>)}</ul></details>}
            <button className="primary" disabled={busy || !doc?.head || Boolean(doc?.blockers.length) || doc?.published === doc?.head || isHistorical} onClick={() => void command({action: "publish", version_id: doc?.head || undefined})}><Check size={14} />{doc?.head && doc?.published === doc?.head ? "Published" : "Publish snapshot"}</button>
            <small>Publishing fixes the version for downstream work. Team approval and Plan handoff are separate.</small>
            {doc?.head && doc.published === doc.head && !isHistorical && kind !== "rfc" && <div className="studio-next-documents"><p>Create another document when useful.</p>{kind === "prd" && <button disabled={busy} onClick={() => switchKind("design")}>Open Design spec <ArrowRight size={14} /></button>}<button disabled={busy} onClick={() => switchKind("rfc")}>Continue to RFC <ArrowRight size={14} /></button>{kind === "prd" && <small>You can use the PRD directly and skip Design.</small>}</div>}
          </div>
        </>}</div>
      </aside></div></>}
    </>}
    {edit && <SectionEditor section={edit.section} onClose={closeEdit} onSave={(text, items) => command({action: "edit", section_id: edit.section.id, version_id: edit.version, text, items})} />}
    {comment && <CommentEditor section={comment.section} quote={comment.quote} onClose={closeComment} onSave={(text, blocking) => command({action: "comment", section_id: comment.section.id, version_id: comment.version, quote: comment.quote, text, blocking})} />}
  </div></div>;
}
