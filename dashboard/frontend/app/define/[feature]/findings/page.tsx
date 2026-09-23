"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useClient, useMutation, useQuery } from "urql";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import {
  Activity,
  ArrowLeft,
  ArrowUpRight,
  Bug,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleDot,
  Code2,
  Copy,
  FileText,
  GitMerge,
  Inbox,
  Link2,
  ListChecks,
  RefreshCw,
  Scissors,
  Search,
  ShieldAlert,
  Sparkles,
  Wrench,
  X,
} from "lucide-react";
import { Header } from "@/components/layout/header";
import { IconRail } from "@/components/landing/IconRail";
import { canFileDefectDraft } from "@/lib/define/defect-draft";
import {
  APPEND_DEFECT_EVIDENCE_MUTATION,
  DECIDE_FINDING_MUTATION,
  DEFECT_DRAFT_QUERY,
  EVIDENCE_FILE_QUERY,
  FEATURE_FINDINGS_QUERY,
  FILE_FINDING_DEFECT_MUTATION,
  GROUP_FINDINGS_MUTATION,
  type DraftView,
  type EvidenceFileView,
  type Finding,
  type FindingView,
} from "@/lib/graphql/queries/feature-defects";

const actionConfig: Record<string, { label: string; description: string; confirm: string }> = {
  fix_in_feature: {
    label: "Send back to task",
    description: "Queue an existing feature task for rework on the next speed run.",
    confirm: "Queue rework",
  },
  create_defect: {
    label: "File new defect",
    description: "Review an editable draft, then create a tracked defect.",
    confirm: "Review defect draft",
  },
  needs_verification: {
    label: "Need more evidence",
    description: "Keep this finding pending until someone verifies it.",
    confirm: "Request verification",
  },
  accept_defer: {
    label: "Defer",
    description: "Record the decision without approving or changing the feature.",
    confirm: "Defer finding",
  },
  false_positive: {
    label: "Dismiss as false positive",
    description: "Close this signal because it does not represent a real issue.",
    confirm: "Dismiss finding",
  },
  duplicate: {
    label: "Link to existing",
    description: "Point this finding at the finding or defect that owns the issue.",
    confirm: "Link duplicate",
  },
};

const resolutionConfig: Record<string, { label: string; color: string; bg: string }> = {
  unresolved: { label: "Unresolved", color: "var(--color-amber)", bg: "rgba(240, 178, 50, 0.10)" },
  filed: { label: "Filed", color: "var(--color-blue)", bg: "rgba(75, 166, 238, 0.10)" },
  needs_verification: { label: "Needs verification", color: "var(--color-violet)", bg: "rgba(139, 92, 246, 0.10)" },
  rework_queued: { label: "Rework queued", color: "var(--color-cyan)", bg: "rgba(68, 221, 238, 0.10)" },
  rework_applied: { label: "Rework applied", color: "var(--color-cyan)", bg: "rgba(68, 221, 238, 0.10)" },
  resolved_by_rework: { label: "Resolved", color: "var(--color-emerald)", bg: "rgba(68, 204, 119, 0.10)" },
  accepted_deferred: { label: "Deferred", color: "var(--color-text-secondary)", bg: "rgba(148, 148, 163, 0.10)" },
  false_positive: { label: "False positive", color: "var(--color-text-secondary)", bg: "rgba(148, 148, 163, 0.10)" },
  duplicate: { label: "Duplicate", color: "var(--color-text-secondary)", bg: "rgba(148, 148, 163, 0.10)" },
  rework_blocked: { label: "Rework blocked", color: "var(--color-red)", bg: "rgba(239, 68, 100, 0.10)" },
};

const sourceLabels: Record<string, string> = {
  diagnose: "Diagnose",
  structured_review: "Code review",
  clean_review: "Clean review",
};

const recommendationLabels: Record<string, string> = {
  investigate: "Investigate",
  fix_in_feature: "Fix in feature",
  fix_scope: "Fix scope",
  needs_verification: "Verify",
  consider_defect: "Consider defect",
  accept: "Accept",
};

const recommendationActions: Record<string, string> = {
  investigate: "needs_verification",
  fix_in_feature: "fix_in_feature",
  fix_scope: "fix_in_feature",
  needs_verification: "needs_verification",
  consider_defect: "create_defect",
  accept: "accept_defer",
};

const controlClass = "h-9 rounded-md border border-border bg-bg-elevated px-3 text-[12px] text-text-secondary outline-none transition-colors hover:border-white/15 focus:border-accent/50 focus:ring-2 focus:ring-accent/10";
const secondaryButtonClass = "inline-flex h-9 items-center justify-center gap-2 rounded-md border border-border bg-bg-elevated px-3 text-[12px] font-medium text-text-secondary transition-all hover:border-white/15 hover:bg-bg-card-hover hover:text-text disabled:pointer-events-none disabled:opacity-35";
const primaryButtonClass = "inline-flex h-9 items-center justify-center gap-2 rounded-md border border-accent/20 bg-accent px-3.5 text-[12px] font-semibold text-[#07130f] shadow-[0_0_20px_rgba(0,212,170,0.12)] transition-all hover:brightness-110 disabled:pointer-events-none disabled:opacity-40";

function plainEvidenceText(value: string): string {
  return value
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\s+/g, " ")
    .trim();
}

function reviewObservations(value: string): string[] {
  const prefix = /^findings summary\s*\(most severe first\)\s*:\s*/i;
  if (!prefix.test(value)) return [];
  const body = value.replace(prefix, "");
  const markers = [...body.matchAll(/(?:^|\s)(\d+)\.\s+(?=\*\*|`|[A-Za-z])/g)];
  if (markers.length < 2) return [];
  return markers.map((marker, index) => {
    const start = (marker.index || 0) + marker[0].length;
    const end = index + 1 < markers.length ? markers[index + 1].index : body.length;
    return plainEvidenceText(body.slice(start, end))
      .replace(/\s*These are observations from the diff only.*$/i, "")
      .trim();
  }).filter(Boolean);
}

function findingDisplayTitle(finding: Finding): string {
  const observations = reviewObservations(finding.title);
  if (observations.length > 1) return `${observations.length} code-review observations need a decision`;
  const title = plainEvidenceText(finding.title);
  return title.length > 220 ? `${title.slice(0, 217).trimEnd()}…` : title;
}

function StatusPill({ resolution, stale }: { resolution: string; stale: boolean }) {
  const config = resolutionConfig[resolution] || {
    label: resolution.replaceAll("_", " "), color: "var(--color-text-secondary)", bg: "rgba(148, 148, 163, 0.10)",
  };
  return (
    <div className="flex items-center gap-1.5">
      {stale && <span className="rounded-full bg-red/10 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-red">Stale</span>}
      <span className="rounded-full px-2.5 py-1 text-[11px] font-medium" style={{ color: config.color, backgroundColor: config.bg }}>
        {config.label}
      </span>
    </div>
  );
}

type EvidenceFileSelection = { findingId: string; evidenceId: string; path: string };

function EvidenceFilePanel({ feature, selection, close }: {
  feature: string;
  selection: EvidenceFileSelection;
  close: () => void;
}) {
  const [{ data, fetching, error }] = useQuery<{ evidenceFile: EvidenceFileView }>({
    query: EVIDENCE_FILE_QUERY,
    variables: {
      featureName: feature,
      findingId: selection.findingId,
      evidenceId: selection.evidenceId,
      sourcePath: selection.path,
    },
  });
  const result = data?.evidenceFile;
  const lines = result?.content?.split("\n") || [];
  const startLine = result?.start_line || 1;
  const errorMessage = error?.message || result?.errors?.[0]?.message;

  return <section aria-label={`Source excerpt for ${selection.path}`} className="mt-3 overflow-hidden rounded-lg border border-blue/20 bg-[#090b10]">
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-bg-elevated px-3.5 py-2.5">
      <div className="flex min-w-0 items-center gap-2">
        <Code2 className="h-3.5 w-3.5 shrink-0 text-blue" />
        <code className="truncate text-[10px] text-text-secondary">{selection.path}</code>
        {result?.truncated && <span className="shrink-0 rounded bg-bg px-1.5 py-0.5 text-[8px] font-semibold uppercase tracking-[0.06em] text-text-tertiary">Excerpt</span>}
      </div>
      <div className="flex items-center gap-1">
        <button
          onClick={() => navigator.clipboard.writeText(result?.content || "")}
          disabled={!result?.content}
          className="rounded-md p-1.5 text-text-tertiary hover:bg-bg-card-hover hover:text-text disabled:opacity-30"
          aria-label="Copy source excerpt"
        ><Copy className="h-3.5 w-3.5" /></button>
        <button onClick={close} className="rounded-md p-1.5 text-text-tertiary hover:bg-bg-card-hover hover:text-text" aria-label="Close source excerpt"><X className="h-3.5 w-3.5" /></button>
      </div>
    </div>
    {fetching && <div className="flex items-center gap-2 px-4 py-8 text-[11px] text-text-secondary"><RefreshCw className="h-3.5 w-3.5 animate-spin" /> Loading source excerpt…</div>}
    {errorMessage && <div role="alert" className="px-4 py-5 text-[11px] text-red">{errorMessage}</div>}
    {result?.success && <p className="border-b border-border/70 px-4 py-2 text-[10px] text-amber">Current workspace file, not a snapshot of the reviewed commit. Check the evidence record before filing.</p>}
    {result?.success && <pre className="max-h-96 overflow-auto py-3 text-[10px] leading-5 text-text-secondary">{lines.map((line, index) => {
      const lineNumber = startLine + index;
      const highlighted = lineNumber === result.highlight_line;
      return <span key={lineNumber} className={`block min-w-max px-3 ${highlighted ? "bg-amber/10 text-text" : ""}`}>
        <span className="mr-4 inline-block w-10 select-none text-right text-text-tertiary">{lineNumber}</span>{line || " "}
      </span>;
    })}</pre>}
  </section>;
}

function FindingActions({ finding, onSelect }: { finding: Finding; onSelect: (action: string) => void }) {
  const recommendedAction = recommendationActions[finding.recommended_action];
  const directActions = recommendedAction && finding.allowed_actions.includes(recommendedAction)
    ? [recommendedAction]
    : [];
  if (["fix_in_feature", "create_defect"].includes(recommendedAction)) {
    const alternative = recommendedAction === "fix_in_feature" ? "create_defect" : "fix_in_feature";
    if (finding.allowed_actions.includes(alternative)) directActions.unshift(alternative);
  }
  const moreActions = finding.allowed_actions.filter((action) => !directActions.includes(action));
  return (
    <div className="flex flex-wrap items-center justify-end gap-2">
      {directActions.map((action) => {
        const config = actionConfig[action];
        const recommended = recommendationActions[finding.recommended_action] === action;
        return <button
          key={action}
          onClick={() => onSelect(action)}
          title={config.description}
          className={recommended ? primaryButtonClass : secondaryButtonClass}
        >
          {recommended && <Sparkles aria-label="Recommended" className="h-3.5 w-3.5" />}
          {action === "create_defect" ? <Bug className="h-3.5 w-3.5" /> : action === "fix_in_feature" ? <Wrench className="h-3.5 w-3.5" /> : <ShieldAlert className="h-3.5 w-3.5" />}
          {config.label}
        </button>;
      })}
      {!!moreActions.length && <DropdownMenu.Root>
        <DropdownMenu.Trigger asChild>
          <button className={secondaryButtonClass}>More actions <ChevronDown className="h-3.5 w-3.5" /></button>
        </DropdownMenu.Trigger>
        <DropdownMenu.Portal>
          <DropdownMenu.Content
            align="end"
            sideOffset={6}
            className="z-50 w-72 rounded-lg border border-border bg-bg-elevated p-1.5 shadow-[0_16px_40px_rgba(0,0,0,0.45)]"
          >
            <div className="px-2.5 py-2 text-[9px] font-semibold uppercase tracking-[0.12em] text-text-tertiary">Other outcomes</div>
            {moreActions.map((action) => {
              const config = actionConfig[action] || { label: action, description: "", confirm: action };
              return <DropdownMenu.Item
                key={action}
                onSelect={() => onSelect(action)}
                className="flex cursor-pointer items-start justify-between gap-3 rounded-md px-2.5 py-2.5 outline-none transition-colors data-[highlighted]:bg-bg-card-hover"
              >
                <span>
                  <span className="block text-[12px] font-medium text-text">{config.label}</span>
                  <span className="mt-0.5 block text-[10px] leading-4 text-text-tertiary">{config.description}</span>
                </span>
                {recommendationActions[finding.recommended_action] === action && <Sparkles aria-label="Recommended" className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" />}
              </DropdownMenu.Item>;
            })}
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>}
    </div>
  );
}

type DecisionValues = { rationale: string; taskId: string | null; duplicateTarget: string | null };

function DecisionDialog({ finding, action, close, submit }: {
  finding: Finding;
  action: string;
  close: () => void;
  submit: (values: DecisionValues) => Promise<string | null>;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const taskIds = [...new Set(finding.evidence.map((item) => item.task_id).filter((value): value is string => Boolean(value)))];
  const [rationale, setRationale] = useState("");
  const [taskId, setTaskId] = useState(taskIds.length === 1 ? taskIds[0] : "");
  const [duplicateTarget, setDuplicateTarget] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const config = actionConfig[action] || { label: action, description: "", confirm: "Confirm" };
  const requiresRationale = ["fix_in_feature", "needs_verification", "accept_defer"].includes(action);
  const canSubmit = (!requiresRationale || Boolean(rationale.trim()))
    && (action !== "fix_in_feature" || Boolean(taskId.trim()))
    && (action !== "duplicate" || Boolean(duplicateTarget.trim()));

  useEffect(() => { dialogRef.current?.showModal(); }, []);

  const confirm = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError("");
    const nextError = await submit({
      rationale: rationale.trim(),
      taskId: action === "fix_in_feature" ? taskId.trim() : null,
      duplicateTarget: action === "duplicate" ? duplicateTarget.trim() : null,
    });
    setSubmitting(false);
    if (nextError) setError(nextError);
    else close();
  };

  return <dialog
    ref={dialogRef}
    onCancel={(event) => { event.preventDefault(); close(); }}
    aria-labelledby="finding-decision-title"
    className="m-auto max-h-[calc(100dvh-32px)] w-[min(520px,calc(100vw-24px))] grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden rounded-xl border border-border bg-bg-elevated p-0 text-text shadow-[0_24px_80px_rgba(0,0,0,0.65)] backdrop:bg-black/70 open:grid"
  >
    <div className="flex items-start justify-between border-b border-border px-5 py-4">
      <div className="min-w-0 pr-4">
        <div className="mb-1.5 text-[9px] font-semibold uppercase tracking-[0.12em] text-accent">Finding outcome</div>
        <h2 id="finding-decision-title" className="text-[17px] font-semibold text-text">{config.label}</h2>
        <p className="mt-1 text-[11px] leading-5 text-text-secondary">{config.description}</p>
      </div>
      <button onClick={close} aria-label="Close decision" className="rounded-md p-2 text-text-tertiary hover:bg-bg-card-hover hover:text-text"><X className="h-4 w-4" /></button>
    </div>

    <div className="min-h-0 overflow-y-auto overscroll-contain px-5 py-5">
      <div className="mb-5 rounded-lg border border-border bg-bg px-3.5 py-3">
        <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-text-tertiary">Finding</div>
        <p className="mt-1.5 text-[12px] font-medium leading-5 text-text">{finding.title}</p>
      </div>

      <div className="grid gap-4">
        {action === "fix_in_feature" && <label className="grid gap-1.5 text-[11px] font-medium text-text-secondary">
          Feature task ID
          <input
            autoFocus
            list="finding-task-options"
            value={taskId}
            onChange={(event) => setTaskId(event.target.value)}
            placeholder="Choose or enter an existing task ID"
            className={`${controlClass} w-full text-text`}
          />
          <datalist id="finding-task-options">{taskIds.map((value) => <option key={value} value={value} />)}</datalist>
          <span className="text-[10px] font-normal text-text-tertiary">This queues rework; it does not run an agent immediately.</span>
        </label>}

        {action === "duplicate" && <label className="grid gap-1.5 text-[11px] font-medium text-text-secondary">
          Existing finding ID or defect slug
          <input autoFocus value={duplicateTarget} onChange={(event) => setDuplicateTarget(event.target.value)} className={`${controlClass} w-full text-text`} />
        </label>}

        {action !== "duplicate" && <label className="grid gap-1.5 text-[11px] font-medium text-text-secondary">
          {action === "false_positive" ? "Notes (optional)" : "Rationale"}
          <textarea
            autoFocus={action !== "fix_in_feature"}
            value={rationale}
            onChange={(event) => setRationale(event.target.value)}
            rows={4}
            placeholder={action === "false_positive" ? "Why is this signal not actionable?" : "Explain why this is the right outcome."}
            className="w-full resize-y rounded-md border border-border bg-bg px-3 py-2.5 text-[12px] leading-5 text-text outline-none focus:border-accent/50 focus:ring-2 focus:ring-accent/10"
          />
        </label>}

        {error && <div role="alert" className="rounded-lg border border-red/20 bg-red/5 px-3 py-2.5 text-[11px] text-red">{error}</div>}
      </div>
    </div>

    <div className="flex items-center justify-end gap-2 border-t border-border bg-bg/60 px-5 py-4">
      <button className={secondaryButtonClass} onClick={close}>Cancel</button>
      <button className={primaryButtonClass} disabled={!canSubmit || submitting} onClick={confirm}>
        {submitting ? <><RefreshCw className="h-3.5 w-3.5 animate-spin" /> Saving…</> : config.confirm}
      </button>
    </div>
  </dialog>;
}

function DraftDialog({ feature, finding, close, refresh }: {
  feature: string; finding: Finding; close: () => void; refresh: () => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const requestIdRef = useRef<string | null>(null);
  const client = useClient();
  const [{ data, fetching, error }] = useQuery<{ defectDraft: DraftView }>({
    query: DEFECT_DRAFT_QUERY, variables: { featureName: feature, findingId: finding.id },
  });
  const [, file] = useMutation(FILE_FINDING_DEFECT_MUTATION);
  const [preview, setPreview] = useState<DraftView | null>(null);
  const [draft, setDraft] = useState<DraftView["draft"] | null>(null);
  const [rationale, setRationale] = useState("");
  const [duplicateReason, setDuplicateReason] = useState("");
  const [result, setResult] = useState<any>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (data?.defectDraft && !preview) {
      setPreview(data.defectDraft);
      setDraft(data.defectDraft.draft);
    }
  }, [data, preview]);
  useEffect(() => { dialogRef.current?.showModal(); }, []);

  const update = (field: string, value: unknown) => setDraft((current) => current ? ({ ...current, [field]: value }) : current);
  const submit = async () => {
    if (!draft || !preview || !canFileDefectDraft(draft, rationale, duplicates.length, duplicateReason)) return;
    setSubmitting(true); setResult(null);
    requestIdRef.current ||= crypto.randomUUID();
    const response = await file({ input: {
      featureName: feature, findingId: finding.id,
      evidenceIds: preview.provenance.evidence_ids,
      findingRevision: preview.finding_revision,
      decisionRevision: preview.decision_revision,
      requestId: requestIdRef.current, rationale, duplicateReason: duplicateReason || null,
      draft: {
        title: draft.title, severity: draft.severity || "", severityConfirmed: draft.severity_confirmed,
        relatedFeatures: draft.related_features, observed: draft.observed, expected: draft.expected,
        reproduction: draft.reproduction, reproducibility: draft.reproducibility,
        lastKnownWorking: draft.last_known_working, environment: draft.environment,
        errorOutput: draft.error_output, context: draft.context,
      },
    }});
    const value = response.data?.fileFindingDefect;
    setResult(value || { success: false, errors: [{ message: response.error?.message || "Filing failed" }] });
    setSubmitting(false);
    if (value?.success) refresh();
    else {
      const field = value?.errors?.[0]?.field;
      const target = field ? dialogRef.current?.querySelector<HTMLElement>(`[name="${field}"]`) : null;
      if (target) target.focus();
      else bodyRef.current?.scrollTo({ top: 0, behavior: "smooth" });
    }
  };
  const refreshEvidence = async () => {
    const response = await client.query<{ defectDraft: DraftView }>(
      DEFECT_DRAFT_QUERY, { featureName: feature, findingId: finding.id }, { requestPolicy: "network-only" },
    ).toPromise();
    const next = response.data?.defectDraft;
    if (!next) { setResult({ success: false, errors: [{ message: response.error?.message || "Refresh failed" }] }); return; }
    if (!window.confirm("Replace the current draft fields with the latest evidence?")) return;
    setPreview(next); setDraft(next.draft); setResult(null); setDuplicateReason("");
    requestIdRef.current = null;
  };
  const duplicates = [...(preview?.duplicates || []), ...(result?.duplicates || [])]
    .filter((item, index, values) => values.findIndex((value) => value.slug === item.slug) === index);
  const canFile = canFileDefectDraft(draft, rationale, duplicates.length, duplicateReason);

  return (
    <dialog
      ref={dialogRef}
      onCancel={(event) => { event.preventDefault(); close(); }}
      aria-labelledby="defect-draft-title"
      className="fixed inset-y-0 right-0 m-0 ml-auto h-[100dvh] max-h-none w-[min(900px,100vw)] max-w-none grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden border-y-0 border-r-0 border-l border-border bg-bg-elevated p-0 text-text shadow-[-24px_0_80px_rgba(0,0,0,0.55)] backdrop:bg-black/70 open:grid"
    >
      <div className="flex items-start justify-between border-b border-border px-5 py-5 sm:px-7">
        <div>
          <div className="mb-2 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-accent">
            <Bug className="h-3.5 w-3.5" /> Defect intake
          </div>
          <h2 id="defect-draft-title" className="text-lg font-semibold tracking-[-0.01em]">Create defect from finding</h2>
          <p className="mt-1 text-[12px] text-text-tertiary">Review the generated draft before anything is written.</p>
        </div>
        <button onClick={close} aria-label="Close defect draft" className="rounded-md p-2 text-text-tertiary transition-colors hover:bg-bg-card-hover hover:text-text">
          <X className="h-4 w-4" />
        </button>
      </div>

      <div ref={bodyRef} className="min-h-0 overflow-y-auto overscroll-contain px-5 py-5 sm:px-7">
        <div className="mx-auto w-full max-w-[760px]">
        <div className="mb-5 flex items-center gap-3 rounded-lg border border-border bg-bg px-3.5 py-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-accent/10 text-accent"><FileText className="h-4 w-4" /></div>
          <div className="min-w-0 flex-1">
            <div className="text-[11px] font-medium text-text">Source finding</div>
            <div className="truncate text-[11px] text-text-tertiary">{feature} · {finding.title}</div>
          </div>
          <span className="rounded-full border border-border px-2 py-1 font-mono text-[9px] text-text-tertiary">NO WRITE</span>
        </div>

        {result && !result.success && <div role="alert" className="mb-5 rounded-lg border border-red/20 bg-red/5 p-3 text-[12px] text-red">
          {result.errors?.map((item: { field?: string; message: string }, index: number) => <div key={index}>{item.field ? `${item.field}: ` : ""}{item.message}</div>)}
        </div>}

        {fetching && <div className="flex items-center gap-2 py-10 text-text-secondary"><RefreshCw className="h-4 w-4 animate-spin" /> Building draft…</div>}
        {error && <div role="alert" className="rounded-lg border border-red/20 bg-red/5 p-3 text-[12px] text-red">{error.message}</div>}
        {draft && <div className="grid gap-5">
          <section className="grid gap-4">
            <div className="type-compact-label">Classification</div>
            <label className="grid gap-1.5 text-[11px] font-medium text-text-secondary">
              Title
              <input name="title" value={draft.title} onChange={(e) => update("title", e.target.value)} maxLength={160} placeholder="Short, specific failure title" className={`${controlClass} w-full text-text`} />
            </label>
            <div className="grid gap-4 sm:grid-cols-[160px_1fr]">
              <label className="grid gap-1.5 text-[11px] font-medium text-text-secondary">
                Severity
                <select name="severity" value={draft.severity || ""} onChange={(e) => update("severity", e.target.value)} className={`${controlClass} w-full`}>
                  <option value="">Choose severity</option>{["P0", "P1", "P2", "P3"].map((value) => <option key={value}>{value}</option>)}
                </select>
              </label>
              <label className="grid gap-1.5 text-[11px] font-medium text-text-secondary">
                Related features
                <input name="relatedFeatures" value={draft.related_features.join(", ")} onChange={(e) => update("related_features", e.target.value.split(",").map((v) => v.trim()).filter(Boolean))} className={`${controlClass} w-full text-text`} />
              </label>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="grid gap-1.5 text-[11px] font-medium text-text-secondary"><span>Reproducibility <span className="text-text-tertiary">(required)</span></span>
                <input name="reproducibility" value={draft.reproducibility} onChange={(e) => update("reproducibility", e.target.value)} placeholder="always, once, or intermittent (3/10)" className={`${controlClass} w-full text-text`} />
              </label>
              <label className="grid gap-1.5 text-[11px] font-medium text-text-secondary"><span>Last known working <span className="text-text-tertiary">(required)</span></span>
                <input name="last_known_working" value={draft.last_known_working} onChange={(e) => update("last_known_working", e.target.value)} placeholder="Version, date, commit, or unknown with explanation" className={`${controlClass} w-full text-text`} />
              </label>
            </div>
            <label className="flex items-center gap-2 rounded-md border border-border bg-bg px-3 py-2.5 text-[11px] text-text-secondary">
              <input name="severityConfirmed" type="checkbox" checked={draft.severity_confirmed} onChange={(e) => update("severity_confirmed", e.target.checked)} className="accent-[var(--color-accent)]" />
              I reviewed and confirm this severity
            </label>
          </section>

          <div className="h-px bg-border" />

          <section className="grid gap-4">
            <div className="type-compact-label">Defect details</div>
            {(["observed", "expected", "reproduction", "environment", "error_output", "context"] as const).map((field) => (
              <label key={field} className="grid gap-1.5 text-[11px] font-medium capitalize text-text-secondary">
                {field === "context" ? "Additional context" : field === "error_output" ? "Error output" : field}
                <textarea
                  name={field}
                  value={draft[field]}
                  onChange={(e) => update(field, e.target.value)}
                  rows={field === "context" ? 5 : 4}
                  placeholder={field === "reproduction" ? "1. Set up the affected state\n2. Run the action or test\n3. Observe the result" : field === "environment" ? "Runtime, OS, test data, and other conditions that matter" : field === "error_output" ? "Paste verbatim failure output, or state explicitly if there was none" : undefined}
                  className="min-h-24 w-full resize-y rounded-md border border-border bg-bg px-3 py-2.5 text-[12px] font-normal leading-5 text-text outline-none transition-colors placeholder:text-text-tertiary focus:border-accent/50 focus:ring-2 focus:ring-accent/10"
                />
              </label>
            ))}
            <label className="grid gap-1.5 text-[11px] font-medium text-text-secondary">
              Filing rationale
              <textarea name="rationale" value={rationale} onChange={(e) => setRationale(e.target.value)} rows={2} className="w-full resize-y rounded-md border border-border bg-bg px-3 py-2.5 text-[12px] font-normal text-text outline-none focus:border-accent/50 focus:ring-2 focus:ring-accent/10" />
            </label>
          </section>

          {!!duplicates.length && <div role="alert" className="rounded-lg border border-amber/20 bg-amber/5 p-4 text-[12px] text-amber">
            <div className="mb-1 flex items-center gap-2 font-semibold"><ShieldAlert className="h-4 w-4" /> Possible duplicate</div>
            <p className="mb-3 text-text-secondary">{duplicates.map((item) => item.title).join(", ")}</p>
            <label className="grid gap-1.5 text-[11px] font-medium text-text-secondary">Reason to file separately
              <textarea name="duplicateReason" value={duplicateReason} onChange={(e) => setDuplicateReason(e.target.value)} rows={2} className="w-full resize-y rounded-md border border-amber/20 bg-bg px-3 py-2 text-text outline-none focus:border-amber/50" />
            </label>
          </div>}
          {result?.success && <div role="status" className="flex items-center gap-2 rounded-lg border border-emerald/20 bg-emerald/5 p-3 text-[12px] text-emerald"><CheckCircle2 className="h-4 w-4" /> Filed <Link className="underline underline-offset-2" href={`/editor?spec=${encodeURIComponent(result.canonical_path)}&return=${encodeURIComponent(`/define/${feature}/findings?finding=${finding.id}`)}`}>{result.canonical_path}</Link></div>}
          {!!result?.warnings?.length && <div role="alert" className="rounded-lg border border-amber/20 bg-amber/5 p-3 text-[12px] text-amber">{result.warnings.join(" · ")}</div>}
        </div>}
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border bg-bg/80 px-5 py-4 sm:px-7">
        <button className={secondaryButtonClass} onClick={refreshEvidence} disabled={!draft || submitting}><RefreshCw className="h-3.5 w-3.5" /> Refresh evidence</button>
        <div className="flex gap-2">
          <button className={secondaryButtonClass} onClick={close}>Cancel</button>
          {!canFile && draft && <span className="self-center text-[11px] text-text-tertiary">Complete required fields to file</span>}
          <button className={primaryButtonClass} disabled={!canFile || submitting || result?.success} onClick={submit}>
            {submitting ? <><RefreshCw className="h-3.5 w-3.5 animate-spin" /> Filing…</> : result?.code === "WRITE_FAILED" || result?.code === "REPAIR_REQUIRED" ? "Retry filing" : <><Bug className="h-3.5 w-3.5" /> File defect</>}
          </button>
        </div>
      </div>
    </dialog>
  );
}

export default function FindingsPage() {
  const { feature } = useParams<{ feature: string }>();
  const searchParams = useSearchParams();
  const requestedReturn = searchParams.get("return");
  const safeReturnPath = requestedReturn && /^\/define\/defects(?:\?[^#]*)?$/.test(requestedReturn)
    ? requestedReturn : null;
  const [{ data, fetching, error }, reload] = useQuery<{ featureFindings: FindingView }>({ query: FEATURE_FINDINGS_QUERY, variables: { featureName: feature } });
  const [, decide] = useMutation(DECIDE_FINDING_MUTATION);
  const [, group] = useMutation(GROUP_FINDINGS_MUTATION);
  const [, appendEvidence] = useMutation(APPEND_DEFECT_EVIDENCE_MUTATION);
  const [resolution, setResolution] = useState("all");
  const [source, setSource] = useState("all");
  const [task, setTask] = useState("");
  const [staleOnly, setStaleOnly] = useState(false);
  const [linkedOnly, setLinkedOnly] = useState(false);
  const [groupingMode, setGroupingMode] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [openFinding, setOpenFinding] = useState<Finding | null>(null);
  const [pendingDecision, setPendingDecision] = useState<{ finding: Finding; action: string } | null>(null);
  const [evidenceFile, setEvidenceFile] = useState<EvidenceFileSelection | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const view = data?.featureFindings;
  useEffect(() => {
    const requested = searchParams.get("finding");
    if (requested && view?.findings.some((item) => item.id === requested)) setExpanded(requested);
  }, [searchParams, view]);
  const findings = useMemo(() => (view?.findings || []).filter((item) =>
    (resolution === "all" || item.resolution === resolution)
    && (source === "all" || item.evidence.some((evidence) => evidence.producer === source))
    && (!task || item.evidence.some((evidence) => evidence.task_id === task))
    && (!staleOnly || item.stale) && (!linkedOnly || Boolean(item.linked_defect_slug))
  ), [view, resolution, source, task, staleOnly, linkedOnly]);

  const changeGrouping = async (mode: "merge" | "split", splitFinding?: Finding) => {
    if (!view) return;
    const chosen = mode === "split" && splitFinding
      ? [splitFinding]
      : view.findings.filter((item) => selected.has(item.id));
    if ((mode === "merge" && chosen.length < 2) || (mode === "split" && chosen.length !== 1)) return;
    const rationale = window.prompt(mode === "merge"
      ? "Why do these findings describe the same underlying issue?"
      : "Why should these evidence items become separate findings?");
    if (!rationale) return;
    const identity = (evidence: Finding["evidence"][number]) => `${evidence.producer}:${evidence.task_id || "_feature"}:${evidence.item_key}`;
    const memberships: Array<{ findingId: string; evidenceIdentities: string[] }> = [];
    const chosenIds = new Set(chosen.map((item) => item.id));
    view.findings.filter((item) => !chosenIds.has(item.id)).forEach((item) => memberships.push({ findingId: item.id, evidenceIdentities: item.evidence.map(identity) }));
    if (mode === "merge") {
      const filed = chosen.filter((item) => item.linked_defect_slug);
      if (filed.length > 1) { setMessage("Two filed findings cannot be merged because each owns a defect link"); return; }
      memberships.push({ findingId: filed[0]?.id || `finding-manual-${crypto.randomUUID()}`, evidenceIdentities: chosen.flatMap((item) => item.evidence.map(identity)) });
    } else chosen[0].evidence.forEach((evidence, index) => memberships.push({ findingId: index === 0 ? chosen[0].id : `finding-split-${crypto.randomUUID()}`, evidenceIdentities: [identity(evidence)] }));
    const response = await group({ input: { featureName: feature, decisionRevision: view.decision_revision, requestId: crypto.randomUUID(), memberships, rationale } });
    const result = response.data?.groupFindings;
    setMessage(result?.success
      ? mode === "merge" ? "Related findings grouped" : "Evidence separated into individual findings"
      : result?.errors?.[0]?.message || response.error?.message || "Grouping failed");
    if (result?.success) {
      setSelected(new Set());
      setGroupingMode(false);
      reload({ requestPolicy: "network-only" });
    }
  };

  const chooseDisposition = (finding: Finding, action: string) => {
    if (action === "create_defect") { setOpenFinding(finding); return; }
    setPendingDecision({ finding, action });
  };

  const recordDisposition = async (finding: Finding, action: string, values: DecisionValues): Promise<string | null> => {
    const response = await decide({ input: {
      featureName: feature, findingId: finding.id, findingRevision: finding.revision,
      decisionRevision: view?.decision_revision || 0, requestId: crypto.randomUUID(),
      action, rationale: values.rationale, taskId: values.taskId,
      duplicateTarget: values.duplicateTarget,
    }});
    const result = response.data?.decideFinding;
    const errorMessage = result?.errors?.[0]?.message || response.error?.message || "Decision failed";
    if (!result?.success) return errorMessage;
    setMessage(`${actionConfig[action]?.label || "Decision"} recorded`);
    reload({ requestPolicy: "network-only" });
    return null;
  };

  const updateEvidence = async (finding: Finding) => {
    if (!finding.linked_defect_slug || !view) return;
    const rationale = window.prompt("Why should this evidence be attached to the existing defect?");
    if (!rationale) return;
    const response = await appendEvidence({ input: {
      featureName: feature, findingId: finding.id, findingRevision: finding.revision,
      decisionRevision: view.decision_revision, requestId: crypto.randomUUID(),
      defectSlug: finding.linked_defect_slug, rationale,
    }});
    const result = response.data?.appendDefectEvidence;
    setMessage(result?.success ? "Evidence attached to the existing defect" : result?.errors?.[0]?.message || response.error?.message || "Evidence update failed");
    if (result?.success) reload({ requestPolicy: "network-only" });
  };

  const allFindings = view?.findings || [];
  const unresolvedCount = allFindings.filter((item) => item.resolution === "unresolved").length;
  const evidenceCount = allFindings.reduce((total, item) => total + item.evidence.length, 0);
  const staleCount = allFindings.filter((item) => item.stale).length;
  const linkedCount = allFindings.filter((item) => item.linked_defect_slug).length;
  const hasFilters = resolution !== "all" || source !== "all" || Boolean(task) || staleOnly || linkedOnly;
  const clearFilters = () => {
    setResolution("all"); setSource("all"); setTask(""); setStaleOnly(false); setLinkedOnly(false);
  };

  return <div className="flex min-h-screen"><IconRail /><div className="min-w-0 flex-1"><Header />
    <main className="mx-auto max-w-[1180px] px-5 pb-20 pt-7 sm:px-7 lg:px-9">
      <header className="mb-7 flex flex-col justify-between gap-5 sm:flex-row sm:items-start">
        <div>
          <Link href={safeReturnPath || `/define/${feature}`} className="mb-3 inline-flex items-center gap-1.5 text-[11px] font-medium text-text-tertiary transition-colors hover:text-text-secondary">
            <ArrowLeft className="h-3.5 w-3.5" /> {safeReturnPath ? "Back to defect report" : feature}
          </Link>
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-accent/15 bg-accent/10 text-accent shadow-[0_0_24px_rgba(0,212,170,0.06)]">
              <Inbox className="h-5 w-5" />
            </div>
            <div>
              <h1 className="font-mono text-[22px] font-semibold tracking-[-0.03em] text-text">Finding inbox</h1>
              <p className="mt-0.5 text-[12px] text-text-secondary">Triage evidence from Diagnose and Review, then choose what happens next.</p>
            </div>
          </div>
        </div>
        <Link href={`/define/defects?feature=${encodeURIComponent(feature)}`} className={secondaryButtonClass}>
          <Bug className="h-3.5 w-3.5" /> Defect report <ArrowUpRight className="h-3.5 w-3.5 text-text-tertiary" />
        </Link>
      </header>

      <section aria-label="Finding summary" className="mb-5 grid grid-cols-2 gap-2.5 lg:grid-cols-4">
        {[
          { label: "Unresolved", value: unresolvedCount, icon: CircleDot, color: "var(--color-amber)", hint: "Awaiting a decision" },
          { label: "Evidence", value: evidenceCount, icon: Activity, color: "var(--color-accent)", hint: "Across all sources" },
          { label: "Stale", value: staleCount, icon: ShieldAlert, color: "var(--color-red)", hint: "Needs another look" },
          { label: "Linked", value: linkedCount, icon: Link2, color: "var(--color-blue)", hint: "Connected to defects" },
        ].map((stat) => <div key={stat.label} className="surface flex min-w-0 items-center gap-3 px-4 py-3.5">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg" style={{ color: stat.color, backgroundColor: `color-mix(in srgb, ${stat.color} 10%, transparent)` }}>
            <stat.icon className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            <div className="flex items-baseline gap-2"><span className="font-mono text-lg font-semibold tabular-nums text-text">{stat.value}</span><span className="text-[11px] font-semibold text-text-secondary">{stat.label}</span></div>
            <div className="truncate text-[10px] text-text-tertiary">{stat.hint}</div>
          </div>
        </div>)}
      </section>

      <section aria-label="Finding filters" className="surface mb-4 overflow-hidden">
        <div className="flex flex-col gap-3 border-b border-border px-3 py-3 lg:flex-row lg:items-center">
          <div className="flex min-w-0 items-center gap-1 overflow-x-auto rounded-md bg-bg p-1">
            {[
              ["all", "All", allFindings.length],
              ["unresolved", "Unresolved", unresolvedCount],
              ["filed", "Filed", allFindings.filter((item) => item.resolution === "filed").length],
              ["needs_verification", "Verification", allFindings.filter((item) => item.resolution === "needs_verification").length],
            ].map(([value, label, count]) => <button
              key={String(value)}
              onClick={() => setResolution(String(value))}
              className={`whitespace-nowrap rounded px-3 py-1.5 text-[11px] font-medium transition-colors ${resolution === value ? "bg-bg-card-hover text-text shadow-sm" : "text-text-tertiary hover:text-text-secondary"}`}
            >{label} <span className="ml-1 font-mono text-[9px] opacity-70">{count}</span></button>)}
          </div>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <select aria-label="Filter by source" value={source} onChange={(e) => setSource(e.target.value)} className={controlClass}>
              <option value="all">All sources</option><option value="diagnose">Diagnose</option><option value="structured_review">Code review</option><option value="clean_review">Clean review</option>
            </select>
            <label className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-tertiary" />
              <input aria-label="Filter by task" value={task} onChange={(e) => setTask(e.target.value)} placeholder="Task ID" className={`${controlClass} w-28 pl-9`} />
            </label>
            <button aria-pressed={staleOnly} onClick={() => setStaleOnly(!staleOnly)} className={`${secondaryButtonClass} ${staleOnly ? "border-red/25 bg-red/5 text-red" : ""}`}><ShieldAlert className="h-3.5 w-3.5" /> Stale</button>
            <button aria-pressed={linkedOnly} onClick={() => setLinkedOnly(!linkedOnly)} className={`${secondaryButtonClass} ${linkedOnly ? "border-blue/25 bg-blue/5 text-blue" : ""}`}><Link2 className="h-3.5 w-3.5" /> Linked</button>
          </div>
        </div>
        <div className={`flex min-h-12 flex-wrap items-center justify-between gap-3 px-4 py-2 ${groupingMode ? "bg-accent/[0.035]" : ""}`}>
          {groupingMode ? <>
            <div className="flex min-w-0 items-center gap-2.5 text-[11px] text-text-secondary">
              <ListChecks className="h-4 w-4 shrink-0 text-accent" />
              <span>Select two or more findings that describe the same underlying issue.</span>
              <span className="flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full bg-accent/10 px-1.5 font-mono text-[10px] text-accent">{selected.size}</span>
            </div>
            <div className="flex items-center gap-2">
              <button className={primaryButtonClass} disabled={selected.size < 2} onClick={() => changeGrouping("merge")}><GitMerge className="h-3.5 w-3.5" /> Group findings</button>
              <button className={secondaryButtonClass} onClick={() => { setGroupingMode(false); setSelected(new Set()); }}>Cancel</button>
            </div>
          </> : <>
            <span className="text-[11px] text-text-tertiary">Showing {findings.length} of {allFindings.length} findings</span>
            <div className="flex items-center gap-3">
              {hasFilters && <button onClick={clearFilters} className="text-[11px] font-medium text-accent hover:underline">Clear filters</button>}
              {allFindings.length > 1 && <button className={secondaryButtonClass} onClick={() => { setGroupingMode(true); setSelected(new Set()); }}><GitMerge className="h-3.5 w-3.5" /> Group related findings</button>}
            </div>
          </>}
        </div>
      </section>

      {message && <div role="status" className="mb-3 flex items-center gap-2 rounded-lg border border-accent/15 bg-accent/5 px-3 py-2.5 text-[11px] text-accent"><CheckCircle2 className="h-3.5 w-3.5" /> {message}</div>}
      {error && <div role="alert" className="mb-3 rounded-lg border border-red/20 bg-red/5 px-3 py-2.5 text-[11px] text-red">{error.message}</div>}
      {view?.warnings.map((warning) => <div role="alert" key={warning} className="mb-3 flex items-center gap-2 rounded-lg border border-amber/20 bg-amber/5 px-3 py-2.5 text-[11px] text-amber"><ShieldAlert className="h-3.5 w-3.5" /> {warning}</div>)}

      <section aria-label="Findings" className="surface overflow-hidden">
        <div className="flex items-center justify-between border-b border-border bg-bg-elevated/60 px-4 py-2.5">
          <span className="type-table-header">Triage queue</span>
          <span className="font-mono text-[10px] text-text-tertiary">{findings.length} visible</span>
        </div>
        {fetching && !view && <div className="flex items-center justify-center gap-2 py-20 text-[12px] text-text-secondary"><RefreshCw className="h-4 w-4 animate-spin" /> Loading findings…</div>}
        {!fetching && !findings.length && <div className="flex flex-col items-center px-6 py-20 text-center">
          <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl border border-border bg-bg-elevated text-text-tertiary"><Inbox className="h-5 w-5" /></div>
          <div className="text-[13px] font-semibold text-text">No findings in this view</div>
          <p className="mt-1 max-w-sm text-[11px] text-text-tertiary">{hasFilters ? "Try clearing a filter to see the full triage queue." : "Diagnose and Review evidence will appear here when it becomes available."}</p>
          {hasFilters && <button onClick={clearFilters} className="mt-4 text-[11px] font-medium text-accent hover:underline">Clear all filters</button>}
        </div>}
        <div>{findings.map((finding) => {
          const isExpanded = expanded === finding.id;
          const producers = [...new Set(finding.evidence.map((item) => item.producer))];
          const taskIds = [...new Set(finding.evidence.map((item) => item.task_id).filter(Boolean))];
          const observations = reviewObservations(finding.title);
          const displayTitle = findingDisplayTitle(finding);
          const isSelected = selected.has(finding.id);
          const canChooseOutcome = ["unresolved", "needs_verification", "rework_blocked"].includes(finding.resolution);
          return <article key={finding.id} className={`border-b border-border/70 last:border-b-0 transition-colors ${isSelected ? "bg-accent/[0.045]" : isExpanded ? "bg-bg-elevated/55" : "hover:bg-bg-elevated/35"}`}>
            <div className="flex items-start gap-3 px-4 py-4 sm:px-5">
              {groupingMode && <label className="mt-1 flex h-5 w-5 shrink-0 items-center justify-center">
                <input aria-label={`Select ${finding.title}`} type="checkbox" checked={selected.has(finding.id)} className="h-3.5 w-3.5 accent-[var(--color-accent)]" onChange={(event) => setSelected((current) => {
                  const next = new Set(current); if (event.target.checked) next.add(finding.id); else next.delete(finding.id); return next;
                })} />
              </label>}
              <button aria-expanded={isExpanded} onClick={() => setExpanded(isExpanded ? null : finding.id)} className="min-w-0 flex-1 text-left">
                <div className="mb-2 flex flex-wrap items-center gap-1.5">
                  {producers.map((producer) => <span key={producer} className="rounded border border-border bg-bg px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.06em] text-text-tertiary">{sourceLabels[producer] || producer}</span>)}
                  {taskIds.map((taskId) => <span key={taskId} className="font-mono text-[9px] text-text-tertiary">TASK-{taskId}</span>)}
                </div>
                <h2 className="max-w-3xl overflow-hidden text-[13px] font-semibold leading-5 text-text [display:-webkit-box] [-webkit-box-orient:vertical] [-webkit-line-clamp:2]">{displayTitle}</h2>
                <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[10px] text-text-tertiary">
                  <span>{finding.evidence.length} evidence {finding.evidence.length === 1 ? "item" : "items"}</span>
                  {observations.length > 1 && <span>{observations.length} observations in an unstructured review</span>}
                  <span className="inline-flex items-center gap-1"><Wrench className="h-3 w-3" /> Recommended: <span className="text-text-secondary">{recommendationLabels[finding.recommended_action] || finding.recommended_action}</span></span>
                </div>
              </button>
              <div className="flex shrink-0 items-center gap-2 pt-0.5">
                <StatusPill resolution={finding.resolution} stale={finding.stale} />
                <button aria-label={isExpanded ? "Collapse finding" : "Expand finding"} onClick={() => setExpanded(isExpanded ? null : finding.id)} className="rounded-md p-1.5 text-text-tertiary transition-colors hover:bg-bg-card-hover hover:text-text">
                  {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                </button>
              </div>
            </div>

            {isExpanded && <div className={`border-t border-border/70 bg-bg/35 px-4 py-4 sm:px-5 ${groupingMode ? "sm:pl-12" : ""}`}>
              <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                <div>
                  <span className="type-compact-label">Evidence supporting this finding</span>
                  <p className="mt-1 text-[10px] text-text-tertiary">Review the source details before choosing an outcome.</p>
                </div>
                {finding.evidence.length > 1 && <button
                  className={secondaryButtonClass}
                  title="Turn each evidence item into a separate finding"
                  onClick={() => changeGrouping("split", finding)}
                ><Scissors className="h-3.5 w-3.5" /> Separate evidence</button>}
              </div>
              <div className="grid gap-2 lg:grid-cols-2">{finding.evidence.map((item) => {
                const hasActionableContext = Boolean(item.files.length || item.observed || item.expected || item.reproduction);
                const itemObservations = reviewObservations(item.summary);
                return <div key={item.id} className={`rounded-lg border border-border bg-bg-elevated px-3.5 py-3 ${finding.evidence.length === 1 ? "lg:col-span-2" : ""}`}>
                <div className="mb-2 flex items-center justify-between gap-3">
                  <span className="text-[10px] font-semibold uppercase tracking-[0.06em] text-accent">{sourceLabels[item.producer] || item.producer}</span>
                  <div className="flex items-center gap-1.5">
                    {item.severity && <span title="Reviewer-assigned severity; confirm defect priority separately" className="rounded-full border border-amber/20 bg-amber/5 px-2 py-0.5 text-[9px] text-amber">Review: {item.severity}</span>}
                    <span className="rounded-full bg-bg px-2 py-0.5 text-[9px] text-text-tertiary">{item.confidence === "unjudged" ? "Unreviewed" : item.confidence}</span>
                  </div>
                </div>
                {itemObservations.length > 1 ? <ol className="grid gap-2.5">
                  {itemObservations.map((observation, index) => <li key={`${item.id}-${index}`} className="flex gap-2.5 text-[11px] leading-5 text-text-secondary">
                    <span className="mt-0.5 flex h-5 min-w-5 items-center justify-center rounded-full bg-bg font-mono text-[9px] text-text-tertiary">{index + 1}</span>
                    <span>{observation}</span>
                  </li>)}
                </ol> : <p className="text-[11px] leading-5 text-text-secondary">{plainEvidenceText(item.summary)}</p>}
                {!!item.files.length && <div className="mt-3 flex flex-wrap gap-1.5">{item.files.map((path) => <button
                  key={path}
                  onClick={() => setEvidenceFile({ findingId: finding.id, evidenceId: item.id, path })}
                  className="inline-flex items-center gap-1.5 rounded border border-blue/15 bg-blue/5 px-2 py-1 font-mono text-[9px] text-blue transition-colors hover:border-blue/30 hover:bg-blue/10"
                  title="Load a read-only source excerpt"
                ><Code2 className="h-3 w-3" /> {path}</button>)}</div>}
                {(item.observed || item.expected || item.reproduction) && <div className="mt-3 grid gap-2 border-t border-border/70 pt-3">
                  {item.observed && <div><div className="text-[9px] font-semibold uppercase tracking-[0.06em] text-text-tertiary">Observed</div><p className="mt-1 whitespace-pre-wrap text-[10px] leading-4 text-text-secondary">{item.observed}</p></div>}
                  {item.expected && <div><div className="text-[9px] font-semibold uppercase tracking-[0.06em] text-text-tertiary">Expected</div><p className="mt-1 whitespace-pre-wrap text-[10px] leading-4 text-text-secondary">{item.expected}</p></div>}
                  {item.reproduction && <div><div className="text-[9px] font-semibold uppercase tracking-[0.06em] text-text-tertiary">Reproduction</div><p className="mt-1 whitespace-pre-wrap text-[10px] leading-4 text-text-secondary">{item.reproduction}</p></div>}
                </div>}
                {!hasActionableContext && <div className="mt-3 rounded-md border border-amber/15 bg-amber/5 px-2.5 py-2 text-[10px] leading-4 text-amber">This source did not include a file, line, or reproduction. Request more evidence before acting.</div>}
                <div className="mt-3 flex min-w-0 items-center gap-1.5 text-text-tertiary" title="Archived evidence record; not an application file">
                  <FileText className="h-3 w-3 shrink-0" /><span className="shrink-0 text-[9px]">Evidence record</span><code className="truncate text-[9px]">{item.artifact_path}</code>
                  <button onClick={() => navigator.clipboard.writeText(item.artifact_path)} aria-label="Copy evidence record path" className="ml-auto shrink-0 rounded p-1 hover:bg-bg-card-hover hover:text-text"><Copy className="h-3 w-3" /></button>
                </div>
              </div>})}</div>
              {evidenceFile?.findingId === finding.id && <EvidenceFilePanel feature={feature} selection={evidenceFile} close={() => setEvidenceFile(null)} />}

              <div className="mt-4 flex flex-col gap-3 border-t border-border/70 pt-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  {finding.linked_defect_slug && <Link className="inline-flex items-center gap-1.5 text-[11px] font-medium text-blue hover:underline" href={`/editor?spec=${encodeURIComponent(`specs/defects/${finding.linked_defect_slug}.md`)}&return=${encodeURIComponent(`/define/${feature}/findings?finding=${finding.id}`)}`}><Link2 className="h-3.5 w-3.5" /> {finding.linked_defect_slug}</Link>}
                  {finding.linked_defect_slug && finding.stale && <button className={secondaryButtonClass} onClick={() => updateEvidence(finding)}><RefreshCw className="h-3.5 w-3.5" /> Update evidence</button>}
                </div>
                {canChooseOutcome && <div className="ml-auto">
                  <div className="mb-2 text-right text-[9px] font-semibold uppercase tracking-[0.08em] text-text-tertiary">Choose what happens next</div>
                  <FindingActions finding={finding} onSelect={(action) => chooseDisposition(finding, action)} />
                </div>}
              </div>
            </div>}
          </article>;
        })}</div>
      </section>
    </main>
    {pendingDecision && <DecisionDialog
      finding={pendingDecision.finding}
      action={pendingDecision.action}
      close={() => setPendingDecision(null)}
      submit={(values) => recordDisposition(pendingDecision.finding, pendingDecision.action, values)}
    />}
    {openFinding && <DraftDialog feature={feature} finding={openFinding} close={() => setOpenFinding(null)} refresh={() => reload({ requestPolicy: "network-only" })} />}
  </div></div>;
}
