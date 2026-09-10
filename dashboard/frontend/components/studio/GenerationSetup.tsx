"use client";

import { useState } from "react";
import { Sparkles } from "lucide-react";
import { labels, type Command, type Feature, type Kind, type SourceMode } from "./types";

export function GenerationSetup({feature, kind, busy, onCommand, includeBrief = true, onOpenSource}: {
  feature: Feature; kind: Kind; busy: boolean; onCommand: (command: Command) => Promise<boolean>;
  includeBrief?: boolean; onOpenSource?: (kind: Kind) => void;
}) {
  const prd = feature.documents.prd, design = feature.documents.design;
  const [mode, setMode] = useState<SourceMode>(kind !== "prd" && prd.published ? "prd" : !includeBrief ? kind === "rfc" && design.published ? "design" : "prd" : "brief");
  const designReady = Boolean(design.published && !(design.published_stale ?? design.stale).length);
  const options: {id:SourceMode; label:string; detail:string; available:boolean}[] = [
    ...(includeBrief ? [{id:"brief" as const,label:"Brief and supporting context",detail:`Create the ${labels[kind]} directly from your brief and saved answers.`,available:true}] : []),
    ...(kind !== "prd" ? [{id:"prd" as const,label:kind === "rfc" ? "Published PRD only (skip Design spec)" : "Published PRD",detail:kind === "rfc" ? "Use the published PRD as the foundation. A Design spec is optional and will not be used." : "Build the experience from the published product direction.",available:Boolean(prd.published)}] : []),
    ...(kind === "rfc" ? [
      {id:"design" as const,label:"Published Design spec only",detail:"Use the published experience decisions. A PRD is optional and will not be added as a separate source.",available:designReady},
      {id:"prd_design" as const,label:"Published PRD and Design spec",detail:"Use both published documents and track changes to both.",available:Boolean(prd.published) && designReady},
    ] : []),
  ];
  const selected = options.find(o => o.id === mode)!;
  const [extra, setExtra] = useState("");
  const sourceKinds: Kind[] = mode === "brief" ? [] : mode === "prd_design" ? ["prd", "design"] : [mode];
  const sourceLabels = sourceKinds.map(k => `${labels[k]} v${feature.documents[k].versions.find(v => v.id === feature.documents[k].published)?.number || "?"}`);
  const newerDrafts = sourceKinds.filter(k => feature.documents[k].head !== feature.documents[k].published).map(k => labels[k]);
  return <form className="studio-generation-setup" onSubmit={e => {e.preventDefault(); if (selected.available && !busy) void onCommand({action:"generate",kind,source_mode:mode,...(extra.trim() ? {text:extra.trim()} : {})});}}>
    <label htmlFor={`generation-source-${kind}`}>Start from</label>
    <select id={`generation-source-${kind}`} value={mode} onChange={e => setMode(e.target.value as SourceMode)} disabled={busy}>
      {options.map(o => <option key={o.id} value={o.id} disabled={!o.available}>{o.label}{!o.available ? " · publish a current version first" : ""}</option>)}
    </select>
    <p>{selected.detail}</p>
    {!includeBrief && !selected.available && <p className="studio-muted">Publish a current source document to use it here, or start from a new description.</p>}
    {selected.available && sourceLabels.length > 0 && <small>Using {sourceLabels.join(" and ")}.{newerDrafts.length > 0 && ` Publish the newer ${newerDrafts.join(" and ")} draft to include its changes.`}</small>}
    {kind === "rfc" && mode === "prd" && design.head && <small>Your Design spec stays in this workspace and can be completed separately.</small>}
    {!includeBrief && onOpenSource && <div className="studio-source-preview-links">{sourceKinds.map(k => <button type="button" key={k} disabled={busy || !feature.documents[k].head} onClick={() => onOpenSource(k)}>Open {labels[k]} to review</button>)}</div>}
    {!includeBrief && <><label htmlFor="source-additional-context">Anything to add? (optional)</label><textarea id="source-additional-context" disabled={busy} rows={3} maxLength={20000} value={extra} onChange={e => setExtra(e.target.value)} placeholder="Add any direction for this document. Your saved brief and selected sources will also be used." /></>}
    <button className="primary" type="submit" disabled={busy || !selected.available}><Sparkles size={16} /> Generate {labels[kind]}</button>
    <small>We’ll ask any necessary questions before creating this document.</small>
  </form>;
}
