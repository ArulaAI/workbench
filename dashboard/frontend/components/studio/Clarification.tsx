import { useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, Check, FileText, Loader2, Sparkles } from "lucide-react";
import type { ClarificationAnswer, ClarificationQuestion, Command, Feature, Operation } from "./types";

type Props = {
  feature: Feature;
  active?: Operation;
  failed?: Operation | null;
  busy: boolean;
  saving: boolean;
  onCommand: (command: Command) => Promise<boolean>;
};

export function ClarificationFlow({feature, active, failed, busy, saving, onCommand}: Props) {
  const intake = feature.intake!;
  const [index, setIndex] = useState(() => Math.max(0, intake.questions.findIndex(q => !intake.answers[q.id])));
  const question = intake.questions[index];
  const answering = intake.status === "awaiting_answers";
  const writing = intake.status === "ready";

  return <main className="studio-intake">
    <section className="studio-intake-main" aria-label="PRD clarification">
      <ol className="studio-intake-steps" aria-label="PRD creation progress">
        <li><Check size={14} /> Brief saved</li>
        <li aria-current={!writing ? "step" : undefined}>{writing ? <Check size={14} /> : <span>2</span>} Clarify</li>
        <li aria-current={writing ? "step" : undefined}><span>3</span> Generate PRD</li>
      </ol>
      {answering && question ? <QuestionStep key={question.id} question={question} answer={intake.answers[question.id]}
        index={index} total={intake.questions.length} busy={busy}
        onBack={() => setIndex(i => Math.max(0, i - 1))}
        onNext={async (choice, text) => {
          const saved = await onCommand({action:"answer_clarification", kind:"prd", question_id:question.id, choice, text});
          if (saved && index < intake.questions.length - 1) setIndex(i => i + 1);
        }} /> : <div className="studio-intake-wait surface">
        <div className="studio-empty-icon">{active ? <Loader2 className="studio-spin" size={28} /> : <FileText size={28} />}</div>
        <h2>{failed ? (writing ? "PRD generation needs attention" : "Brief review needs attention") : writing ? "Creating your first PRD" : "Reviewing your brief"}</h2>
        <p role="status">{failed ? failed.error : writing ? "Your brief and saved decisions are ready. We’re using them to write your PRD." : "We’re checking for decisions that need your input before drafting. If your brief is complete, generation starts directly."}</p>
        {active && <button disabled={saving} onClick={() => void onCommand({action:"cancel", kind:"prd"})}>Cancel {writing ? "generation" : "brief review"}</button>}
        {failed && <button className="primary" disabled={busy} onClick={() => void onCommand({action:"retry", kind:"prd"})}>Retry saved request <ArrowRight size={14} /></button>}
        {writing && intake.questions.length > 0 && <div className="studio-intake-decisions"><h3>Your saved decisions</h3>{intake.questions.map(q => <div key={q.id}><strong>{q.question}</strong><p>{intake.answers[q.id]?.text}</p></div>)}</div>}
      </div>}
    </section>
    <aside className="studio-intake-context">
      <div className="surface"><span className="studio-eyebrow"><FileText size={14} /> YOUR BRIEF</span><h2>{feature.title}</h2><p>{feature.brief}</p>{feature.context && <details><summary>Supporting context</summary><p>{feature.context}</p></details>}</div>
      <p>{answering ? "Choose a suggestion or write your own answer. Next saves your response. The PRD will start only after every question is answered." : "Your brief and answers are saved to this workspace. You can leave and come back."}</p>
    </aside>
  </main>;
}

function QuestionStep({question, answer, index, total, busy, onBack, onNext}: {
  question: ClarificationQuestion; answer?: ClarificationAnswer; index: number; total: number; busy: boolean;
  onBack: () => void; onNext: (choice: ClarificationAnswer["choice"], text: string) => Promise<void>;
}) {
  const [choice, setChoice] = useState<ClarificationAnswer["choice"] | "">(answer?.choice || "");
  const [custom, setCustom] = useState(answer?.choice === "custom" ? answer.text : "");
  const heading = useRef<HTMLHeadingElement>(null), customInput = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {heading.current?.focus();}, []);
  useEffect(() => {if (choice === "custom") customInput.current?.focus();}, [choice]);
  const last = index === total - 1;
  return <form className="studio-clarification-card surface" onSubmit={e => {
    e.preventDefault();
    if (choice && !busy && (choice !== "custom" || custom.trim())) void onNext(choice, choice === "custom" ? custom.trim() : "");
  }}>
    <div className="studio-clarification-count"><span>Decision needed</span><span>Question {index + 1} of {total}</span></div>
    <h2 id="clarification-question" tabIndex={-1} ref={heading}>{question.question}</h2>
    <p id="clarification-why" className="studio-clarification-why">{question.why}</p>
    <fieldset aria-labelledby="clarification-question" aria-describedby="clarification-why" disabled={busy}>
      <legend className="sr-only">Choose an answer</legend>
      {question.options.map((option, i) => {
        const value = `option-${i + 1}` as ClarificationAnswer["choice"];
        return <label className={`studio-answer-option surface ${choice === value ? "selected" : ""}`} key={value}>
          <input type="radio" name="clarification-answer" value={value} checked={choice === value} onChange={() => setChoice(value)} />
          <span><strong>{option.label}</strong><span>{option.description}</span></span>
        </label>;
      })}
      <label className={`studio-answer-option surface ${choice === "custom" ? "selected" : ""}`}>
        <input type="radio" name="clarification-answer" value="custom" checked={choice === "custom"} onChange={() => setChoice("custom")} />
        <span><strong>Write my own</strong><span>Describe the direction you want in your own words.</span></span>
      </label>
      {choice === "custom" && <div className="studio-custom-answer"><label htmlFor="clarification-custom">Your answer</label><textarea id="clarification-custom" ref={customInput} rows={4} maxLength={4000} value={custom} onChange={e => setCustom(e.target.value)} placeholder="Tell us what works for this feature…" required /></div>}
    </fieldset>
    <footer><button type="button" disabled={busy || index === 0} onClick={onBack}><ArrowLeft size={14} /> Back</button>
      <button className="primary" type="submit" disabled={busy || !choice || (choice === "custom" && !custom.trim())}>{busy ? <Loader2 className="studio-spin" size={14} /> : last ? <Sparkles size={14} /> : null}{last ? "Generate PRD" : "Next"}{!last && <ArrowRight size={14} />}</button>
    </footer>
    <p className="studio-clarification-note">{last ? "Submitting this answer starts generation with all your decisions." : "Your answer is saved when you select Next."}</p>
  </form>;
}
