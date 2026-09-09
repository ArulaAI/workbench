"use client";

import { useState } from "react";
import type { Command, PublicationReview } from "./types";

type Assessment = "answer" | "confirmed" | "deferred" | "";

export function PublicationReviewCard({ review, version, busy, published, onSave, onEditSection }: {
  review: PublicationReview; version: string; busy: boolean; published: boolean;
  onSave: (command: Command) => Promise<boolean>;
  onEditSection?: (id: string) => void;
}) {
  const [assessment, setAssessment] = useState<Assessment>("");
  const [note, setNote] = useState(""), [answer, setAnswer] = useState("");
  const [failed, setFailed] = useState(false), [submitted, setSubmitted] = useState(false);
  const saved = review.acknowledgement;
  const success = review.id === "success";
  const title = success ? "Review Success before publishing" : "Review Open questions before publishing";
  const answerLabel = success ? "Update the success criteria" : "Answer and update the document";
  const canSubmit = assessment === "answer" ? Boolean(answer.trim()) : assessment === "confirmed" ? !review.requires_deferral : assessment === "deferred" && Boolean(note.trim());

  async function submit() {
    if (!canSubmit || busy || published) return;
    setFailed(false); setSubmitted(false);
    if (assessment === "answer") {
      const text = `Apply these author answers to the ${review.title} publication review. Update the relevant document content and remove only questions these answers actually resolve. Preserve unanswered questions, uncertainty, and existing item identities. Do not treat this request as publication or an acknowledgement.\n\nAuthor answers:\n${answer.trim()}`;
      const accepted = await onSave({action:"revise", version_id:version, text, ...(success ? {section_id:"success"} : {})});
      setFailed(!accepted); setSubmitted(accepted);
    } else {
      if (!await onSave({action:"acknowledge_publication", review_group:review.id, version_id:version, disposition:assessment as "confirmed" | "deferred", text:assessment === "deferred" ? note.trim() : ""})) setFailed(true);
    }
  }

  return <div className="studio-publication-review surface" id={`publication-review-${review.id}`} role="region" aria-label={title}>
    <div className="studio-review-card-heading"><h3>{title}</h3><span className="studio-pill">{saved ? saved.disposition === "deferred" ? "Deferred · still open" : "Confirmed" : review.legacy_published ? "Previously published" : "Your review needed"}</span></div>
    <p>{success ? "Review the success signals, targets, measurement approach and ownership. Add missing details now, or record why they can wait." : "Have answers? Add them here to update the document. If an item can wait, record a follow-up decision instead."}</p>
    <div className="studio-review-section-links">{review.sections.map(s => <div key={s.id}><a href={`#section-${s.id}`}>Read {s.title}</a>{!published && onEditSection && <button type="button" disabled={busy} onClick={() => onEditSection(s.id)}>Edit {s.title} directly</button>}</div>)}</div>
    {review.findings.length > 0 && <details open={!saved}><summary>{review.findings.length} text item{review.findings.length === 1 ? "" : "s"} to review</summary>
      <ul>{review.findings.map((finding, index) => <li key={index}><a href={`#${finding.anchor}`}>{finding.location}</a><blockquote>{finding.excerpt}</blockquote></li>)}</ul>
    </details>}
    {saved ? <div className="studio-review-saved"><p>{saved.disposition === "confirmed" ? "You confirmed this content for this version." : "You chose to leave these items open for follow-up. The note records that decision; it does not answer them."}</p>{saved.note && <blockquote>{saved.note}</blockquote>}
      {!published && <button disabled={busy} onClick={async () => {setFailed(false); setNote(saved.note); setAssessment(saved.disposition); if (!await onSave({action:"revoke_publication_review", review_group:review.id, version_id:version})) setFailed(true);}}>Change {review.title} review</button>}
    </div> : review.legacy_published ? <p>This snapshot was published before author review was introduced. Its next revision will need your review.</p> : <form onSubmit={e => {e.preventDefault(); void submit();}}>
      <fieldset disabled={busy || published}><legend>What would you like to do?</legend>
        <label className="studio-review-choice"><input type="radio" name={`review-${review.id}`} checked={assessment === "answer"} onChange={() => {setAssessment("answer"); setFailed(false);}} /><span>{answerLabel}</span></label>
        <label className="studio-review-choice"><input type="radio" name={`review-${review.id}`} checked={assessment === "deferred"} onChange={() => {setAssessment("deferred"); setFailed(false);}} /><span>Leave these items open for follow-up</span></label>
        {!review.requires_deferral && <label className="studio-review-choice"><input type="radio" name={`review-${review.id}`} checked={assessment === "confirmed"} onChange={() => {setAssessment("confirmed"); setFailed(false);}} /><span>{success ? "I confirm these success criteria" : "I confirm there are no unresolved questions"}</span></label>}
        {review.requires_deferral && <p className="studio-review-hint">Confirmation is unavailable because the document still lists unresolved details above. Answer or edit them, then review the updated version to confirm.</p>}
        {assessment === "answer" && <>
          <label htmlFor={`review-answer-${review.id}`}>{success ? "Success criteria and missing details" : "Your answers or decisions"}</label>
          <textarea id={`review-answer-${review.id}`} rows={4} required maxLength={12000} value={answer} onChange={e => setAnswer(e.target.value)} placeholder={success ? "Identify the metric or row and provide the target, measurement approach or owner you want to use." : "Name the question or open item, then give your answer. You can answer some items now and leave the rest open."} />
          <p>A new version will use your answers. Review the changes before confirming. You can also use the section editor above to update the text directly.</p>
        </>}
        {assessment === "deferred" && <>
          <p>These items stay unresolved. Record why work can proceed while they wait. Other publication checks still apply.</p>
          <label htmlFor={`review-note-${review.id}`}>Reason for deferring and follow-up plan</label>
          <textarea id={`review-note-${review.id}`} rows={3} required maxLength={4000} value={note} onChange={e => setNote(e.target.value)} placeholder="For example: Confirm measurement ownership before launch. It can wait while we review the proposal. Add an owner or follow-up date if known." />
        </>}
        <button className={assessment === "answer" ? "primary" : undefined} type="submit" disabled={!canSubmit}>{assessment === "answer" ? "Update document with answers" : assessment === "deferred" ? "Save follow-up decision" : `Save ${review.title} confirmation`}</button>
      </fieldset>
    </form>}
    {submitted && <p role="status">Your answers are saved in the conversation. A new version has been requested. <a href="#studio-conversation">View generation status</a>.</p>}
    {failed && <p role="alert">Your {assessment === "answer" ? "answers" : "review"} could not be saved. Your text is still here; check the latest version and try again.</p>}
  </div>;
}
