"use client";

import { LockKeyhole, MessageSquare, Sparkles } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Command, PublicationReview, Section, Snapshot } from "./types";
import { PublicationReviewCard } from "./PublicationReview";

export function SectionContent({ section, anchors = false }: { section: Section; anchors?: boolean }) {
  return <div className="studio-prose">
    <ReactMarkdown remarkPlugins={[remarkGfm]} disallowedElements={["img"]}>{section.body}</ReactMarkdown>
    {section.items.length > 0 && <div className="studio-table-scroll"><table>
      <thead><tr><th>ID</th><th>{section.id === "stories" ? "User outcome" : "Statement"}</th><th>{section.id === "requirements" ? "Acceptance criterion" : "Verification / outcome"}</th></tr></thead>
      <tbody>{section.items.map(item => <tr key={item.id} id={anchors ? `item-${item.id}` : undefined}>
        <td><code>{item.id}</code>{item.references.length > 0 && <small>{item.references.join(", ")}</small>}</td>
        <td>{item.statement}</td><td>{item.verification}</td>
      </tr>)}</tbody>
    </table></div>}
  </div>;
}

export function DocumentCanvas({ snapshot, busy, historical, onEdit, onComment, onScope, onReview, publicationReviews = [], published = false, onAcknowledge, demo = false }: {
  demo?: boolean; snapshot: Snapshot; busy: boolean; historical: boolean;
  onEdit: (section: Section) => void; onComment: (section: Section, quote: string) => void;
  onScope: (id: string) => void; onReview: (id: string) => void;
  publicationReviews?: PublicationReview[]; published?: boolean; onAcknowledge?: (command: Command) => Promise<boolean>;
}) {
  const successReview = publicationReviews.find(r => r.id === "success");
  const questionsReview = publicationReviews.find(r => r.id === "open_questions");
  return <div className="studio-document">
    <p className="studio-document-note">{historical ? "Immutable saved version" : "Working document"} <span>·</span> {snapshot.sections.length} sections <span>·</span> v{snapshot.number}</p>
    {snapshot.sections.map((section, index) => <section className="studio-section" key={section.id} id={`section-${section.id}`}>
      <div className="studio-section-heading"><h2><span>{String(index + 1).padStart(2, "0")}</span>{section.title}</h2>
        <div className="studio-section-actions">
          {section.protected && <span title="Directly edited. Whole-document AI requests preserve this section." className="studio-protected"><LockKeyhole size={12} /> Protected</span>}
          {!historical && !demo && <><button disabled={busy} title={`Revise ${section.title} in chat`} aria-label={`Revise ${section.title} in chat`} onClick={() => onScope(section.id)}><Sparkles size={14} /></button>
            </>}
          <button disabled={busy} title={`Comment on ${section.title}`} aria-label={`Comment on ${section.title}`} onClick={() => {
            const selected = window.getSelection()?.toString() || "";
            onComment(section, selected && section.body.includes(selected) ? selected : "");
          }}><MessageSquare size={14} /></button>
        </div>
      </div>
      {section.needs_review && <div className="studio-notice">Your text was preserved after an upstream change. Review it against the new sources.
        {!historical && <button disabled={busy} onClick={() => onReview(section.id)}>Mark section reviewed</button>}</div>}
      <SectionContent section={section} anchors />
      {!historical && section.id === "success" && successReview && onAcknowledge && <PublicationReviewCard demo={demo} key={`${snapshot.id}-success`} review={successReview} version={snapshot.id} busy={busy} published={published} onSave={onAcknowledge} onEditSection={id => {const section = snapshot.sections.find(s => s.id === id); if (section) onEdit(section);}} />}
      {Boolean(section.unverified_source_ids?.length) && <div className="studio-notice">Evidence references need verification: {section.unverified_source_ids!.join(", ")}. Ask for a revision using the available sources before publishing.</div>}
      {section.source_ids.length > 0 && <div className="studio-citations">Based on {section.source_ids.map(id => <a key={id} href={`#source-${id}`}>{snapshot.sources.find(s => s.id === id)?.label || id}</a>)}</div>}
    </section>)}
    {snapshot.assumptions.length > 0 && <section className="studio-section" id="section-assumptions"><h2>Proposed assumptions</h2><p className="studio-muted">Review these before treating them as settled decisions.</p><ul>{snapshot.assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul></section>}
    {(snapshot.questions.length > 0 || !historical && questionsReview) && <section className="studio-section" id="section-open-decisions"><h2>Open questions</h2>{snapshot.questions.map(q => <div key={q.id} id={`question-${q.id}`} className="studio-decision"><strong>{q.question}</strong><p>{q.why}</p><small>{questionsReview?.acknowledgement?.disposition === "deferred" ? "Deferred for follow-up; remains open" : "Answer below to update the document, or leave this question open with a follow-up decision."}</small></div>)}
      {!historical && questionsReview && onAcknowledge && <PublicationReviewCard demo={demo} key={`${snapshot.id}-open-questions`} review={questionsReview} version={snapshot.id} busy={busy} published={published} onSave={onAcknowledge} onEditSection={id => {const section = snapshot.sections.find(s => s.id === id); if (section) onEdit(section);}} />}
    </section>}
    {snapshot.coverage.length > 0 && <section className="studio-section" id="section-rfc-coverage"><h2>RFC coverage</h2><div className="studio-coverage">{snapshot.coverage.map(c => <div key={c.module}><div><strong>{c.module.replaceAll("_", " ")}</strong><span className={`studio-pill ${c.status === "unresolved" ? "amber" : ""}`}>{c.status.replaceAll("_", " ")}</span></div><p>{c.rationale}</p></div>)}</div></section>}
    <section className="studio-section" id="section-sources"><h2>Sources and provenance</h2><p className="studio-muted">Repository excerpts support technical context. Customer evidence comes from the author. Generated proposals still need review.</p>
      {snapshot.sources.map(s => <details className="studio-source" id={`source-${s.id}`} key={s.id}><summary>{s.label}<span>{s.truncated ? "Excerpt" : "Full source"}</span></summary><code>{s.sha256}</code><pre>{s.text}</pre></details>)}
      <p className="studio-muted">Generated with {snapshot.model}. This snapshot has not been automatically approved for Plan.</p>
    </section>
  </div>;
}

export function VersionComparison({ before, after, versionLabels = {} }: { before: Snapshot | null; after: Snapshot; versionLabels?: Record<string, string> }) {
  const changed = after.sections.filter(s => JSON.stringify(before?.sections.find(old => old.id === s.id)) !== JSON.stringify(s));
  const removed = before?.sections.filter(s => !after.sections.some(current => current.id === s.id)) || [];
  const changeCount = changed.length + removed.length;
  return <div className="studio-comparison">
    <div className="studio-comparison-heading"><h2>{changeCount} changed section{changeCount !== 1 ? "s" : ""}</h2><p>v{before?.number || 0} → v{after.number} · {after.summary}</p></div>
    {changed.map(section => {
      const old = before?.sections.find(s => s.id === section.id);
      return <section key={section.id}><h3>{section.title}</h3><div className="studio-compare-columns"><div><p className="studio-diff-label">Before · v{before?.number || 0}</p>{old ? <SectionContent section={old} /> : <p className="studio-muted">Section added</p>}</div><div><p className="studio-diff-label">After · v{after.number}</p><SectionContent section={section} /></div></div></section>;
    })}
    {removed.map(section => <section key={section.id}><h3>{section.title}</h3><div className="studio-compare-columns"><div><p className="studio-diff-label">Before · v{before?.number}</p><SectionContent section={section} /></div><div><p className="studio-diff-label">After · v{after.number}</p><p className="studio-muted">Section removed</p></div></div></section>)}
    {changeCount === 0 && <p className="studio-muted">The section text is unchanged. Review the decision, assumption and source changes below.</p>}
    <details className="studio-source"><summary>Decision, assumption and source changes</summary><div className="studio-compare-columns">{[before, after].map((version, index) => <div key={index} className="studio-prose"><p className="studio-diff-label">{index ? "After" : "Before"} · v{version?.number || 0}</p><h3>Open decisions</h3>{version?.questions.length ? <ul>{version.questions.map(q => <li key={q.id}>{q.question} {q.blocking && "(Blocks publication)"}</li>)}</ul> : <p>None</p>}<h3>Assumptions</h3>{version?.assumptions.length ? <ul>{version.assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul> : <p>None</p>}<h3>Published sources</h3><p>{Object.values(version?.pins || {}).map(id => versionLabels[id] || "Published source").join(", ") || "Author brief and supporting context"}</p>{version?.coverage.length ? <><h3>RFC coverage</h3><ul>{version.coverage.map(c => <li key={c.module}>{c.module.replaceAll("_", " ")}: {c.status.replaceAll("_", " ")}. {c.rationale}</li>)}</ul></> : null}</div>)}</div></details>
  </div>;
}
