"use client";

import { useState } from "react";
import type { Command, PublicationReview } from "./types";

export function PublicationReviewCard({ review, version, busy, published, onSave }: {
  review: PublicationReview; version: string; busy: boolean; published: boolean;
  onSave: (command: Command) => Promise<boolean>;
}) {
  const [disposition, setDisposition] = useState<"confirmed" | "deferred" | "">("");
  const [note, setNote] = useState("");
  const [failed, setFailed] = useState(false);
  const saved = review.acknowledgement;
  const title = review.id === "success" ? "Review Success before publishing" : "Review Open questions before publishing";
  return <div className="studio-publication-review surface" id={`publication-review-${review.id}`} role="region" aria-label={title}>
    <div className="studio-review-card-heading"><h3>{title}</h3><span className="studio-pill">{saved ? saved.disposition === "deferred" ? "Acknowledged · still open" : "Confirmed" : review.legacy_published ? "Previously published" : "Your review needed"}</span></div>
    <p>{review.id === "success" ? "Validate the success signals, targets, measurement approach and ownership. If some details can wait, record that decision explicitly." : "Review the questions and decisions listed here, including those in the linked section. Confirm they are settled, or acknowledge what can remain open in this published version."}</p>
    {review.id === "open_questions" && <div className="studio-review-section-links">{review.sections.map(s => <a key={s.id} href={`#section-${s.id}`}>Read {s.title}</a>)}</div>}
    {review.findings.length > 0 && <details open={!saved}><summary>{review.findings.length} text item{review.findings.length === 1 ? "" : "s"} to review</summary>
      <ul>{review.findings.map((finding, index) => <li key={index}><a href={`#${finding.anchor}`}>{finding.location}</a><blockquote>{finding.excerpt}</blockquote></li>)}</ul>
    </details>}
    {saved ? <div className="studio-review-saved"><p>{saved.disposition === "confirmed" ? "You confirmed this content for this version." : "You acknowledged the unresolved details for this version. They remain open."}</p>{saved.note && <blockquote>{saved.note}</blockquote>}
      {!published && <button disabled={busy} onClick={async () => {setFailed(false); setNote(saved.note); setDisposition(saved.disposition); if (!await onSave({action:"revoke_publication_review", review_group:review.id, version_id:version})) setFailed(true);}}>Change {review.title} review</button>}
    </div> : review.legacy_published ? <p>This snapshot was published before author review was introduced. Its next revision will need your acknowledgement.</p> : <form onSubmit={async e => {
      e.preventDefault(); if (!disposition || disposition === "deferred" && !note.trim()) return;
      setFailed(false);
      if (!await onSave({action:"acknowledge_publication",review_group:review.id,version_id:version,disposition,text:note.trim()})) setFailed(true);
    }}>
      <fieldset disabled={busy || published}><legend>Your assessment</legend>
        <label className="studio-review-choice"><input type="radio" name={`review-${review.id}`} checked={disposition === "confirmed"} disabled={review.requires_deferral} onChange={() => setDisposition("confirmed")} /><span>{review.id === "success" ? "I confirm these success criteria" : "I confirm there are no unresolved questions"}</span></label>
        <label className="studio-review-choice"><input type="radio" name={`review-${review.id}`} checked={disposition === "deferred"} onChange={() => setDisposition("deferred")} /><span>I acknowledge the unresolved details and can publish with them open</span></label>
        {review.requires_deferral && <p className="studio-review-hint">The text above still contains unresolved details. Edit them first to confirm, or acknowledge them with a note.</p>}
        {disposition === "deferred" && <><label htmlFor={`review-note-${review.id}`}>What remains open, and why can it wait?</label><textarea id={`review-note-${review.id}`} rows={3} required maxLength={4000} value={note} onChange={e => setNote(e.target.value)} placeholder="Include an owner or follow-up when known. Your note stays with the published version." /></>}
        <button type="submit" disabled={!disposition || disposition === "deferred" && !note.trim()}>Save {review.title} acknowledgement</button>
      </fieldset>
    </form>}
    {failed && <p role="alert">Your review could not be saved. Your note is still here; check the latest version and try again.</p>}
  </div>;
}
