"use client";

import { useState, useRef, useMemo, useEffect, useCallback } from "react";
import { useQuery, useMutation, useSubscription } from "urql";
import {
  BookOpen,
  Network,
  ChevronRight,
  Loader2,
  Sparkles,
  Wand2,
  Check,
  Shield,
  AlertTriangle,
} from "lucide-react";
import {
  LESSONS_QUERY,
  CONVENTIONS_QUERY,
  CODEBASE_CONTEXT_QUERY,
  RELATED_SPECS_QUERY,
  SPEC_TRACEABILITY_QUERY,
  FEATURE_HEALTH_QUERY,
  AVAILABLE_MODELS_QUERY,
  DETECT_AMBIGUITIES_MUTATION,
  SUGGEST_FIX_MUTATION,
  RUN_AUDIT_MUTATION,
  LATEST_AUDIT_QUERY,
  RECENT_AUDITS_QUERY,
  AUDIT_COMPLETED_SUBSCRIPTION,
  AUDIT_STATUS_QUERY,
  type Lesson,
  type FixSuggestionResult,
  type SpeedAuditResult,
  type AuditIssue,
  type AuditRunStatus,
  type AuditStatus,
  type Convention,
  type CodebaseContext,
  type SpecRelation,
  type SpecTraceability,
  type FeatureHealth,
  type LLMModel,
  type UnconfiguredProvider,
  type AmbiguityReport,
} from "@/lib/graphql/queries/editor";

/* ── Helpers ──────────────────────────────────────────────────── */

function specTypeFromPath(path: string): { label: string; color: string } {
  if (path.includes("/product/")) return { label: "PRD", color: "var(--color-emerald)" };
  if (path.includes("/tech/")) return { label: "RFC", color: "var(--color-blue)" };
  if (path.includes("/design/")) return { label: "DSN", color: "var(--color-violet)" };
  if (path.includes("/defects/")) return { label: "DEF", color: "var(--color-red)" };
  return { label: "SPEC", color: "var(--color-text-tertiary)" };
}

function SpecLabel({ path }: { path: string }) {
  const name = path.split("/").pop()?.replace(".md", "") || path;
  const { label, color } = specTypeFromPath(path);
  return (
    <>
      <span style={{
        fontFamily: "var(--font-mono)", fontSize: 9, fontWeight: 600,
        color, flexShrink: 0,
      }}>
        {label}
      </span>
      <span className="intel-relation-path">{name}</span>
    </>
  );
}

function truncate(text: string, max = 65): string {
  if (text.length <= max) return text;
  const dot = text.indexOf(". ");
  if (dot > 0 && dot <= max) return text.slice(0, dot + 1);
  return text.slice(0, max) + "\u2026";
}

function severityColor(sev: string): string {
  if (sev === "error" || sev === "critical") return "var(--color-red)";
  if (sev === "warning" || sev === "major") return "var(--color-amber)";
  return "var(--color-text-tertiary)";
}

function severityIcon(sev: string): string {
  if (sev === "error" || sev === "critical") return "\u2715";
  if (sev === "warning" || sev === "major") return "\u26A0";
  return "\u00B7";
}

/* ── Shared components ────────────────────────────────────────── */

type IntelTab = "findings" | "reference" | "health";

function TabButton({
  active, onClick, icon: Icon, label,
}: {
  active: boolean; onClick: () => void; icon: typeof BookOpen; label: string;
}) {
  return (
    <button className="intel-tab-btn" data-active={active ? "true" : "false"} onClick={onClick}>
      <Icon size={12} strokeWidth={1.5} />
      {label}
    </button>
  );
}

function Section({
  title, count, defaultOpen, children,
}: {
  title: string; count?: number; defaultOpen?: boolean; children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen ?? true);
  return (
    <div className="intel-section">
      <button className="intel-section-header" onClick={() => setOpen(!open)}>
        <ChevronRight size={10} strokeWidth={2} className="intel-section-chevron" data-open={open ? "true" : "false"} />
        <span className="intel-section-title">{title}</span>
        {count !== undefined && <span className="intel-section-count">{count}</span>}
      </button>
      <div className="intel-section-body" data-open={open ? "true" : "false"}>
        <div style={{ overflow: "hidden" }}>{children}</div>
      </div>
    </div>
  );
}

const INTEL_TAB_KEY = "speed_intel_tab";

/* ── Unified finding model ────────────────────────────────────── */

interface UnifiedFinding {
  id: string;
  source: "audit" | "criteria";
  section: string;
  severity: string;
  level?: number;
  title: string;
  detail: string;
  criterionText?: string;
  suggestedClause?: string;
  delta?: "new" | "persistent" | "resolved";
}

function issueKey(i: AuditIssue): string {
  return `${i.section}::${i.message.slice(0, 80)}`;
}

function buildFindings(
  audit: SpeedAuditResult | null | undefined,
  previousAudit: SpeedAuditResult | null | undefined,
  ambiguity: AmbiguityReport | null | undefined,
): UnifiedFinding[] {
  const out: UnifiedFinding[] = [];

  // Build set of previous audit issue keys for delta computation
  const prevKeys = new Set<string>();
  if (previousAudit?.issues) {
    for (const i of previousAudit.issues) prevKeys.add(issueKey(i));
  }
  const currentKeys = new Set<string>();

  if (audit?.issues) {
    for (let i = 0; i < audit.issues.length; i++) {
      const f = audit.issues[i];
      const key = issueKey(f);
      currentKeys.add(key);
      const delta = prevKeys.size === 0 ? undefined
        : prevKeys.has(key) ? "persistent" as const
        : "new" as const;
      out.push({
        id: `audit-${i}`,
        source: "audit",
        section: f.section || "General",
        severity: f.severity,
        level: f.level,
        title: truncate(f.message),
        detail: f.message,
        delta,
      });
    }
  }

  // Resolved: in previous but not in current
  if (previousAudit?.issues && audit) {
    for (const prev of previousAudit.issues) {
      if (!currentKeys.has(issueKey(prev))) {
        out.push({
          id: `resolved-${prev.section}-${prev.message.slice(0, 20)}`,
          source: "audit",
          section: prev.section || "General",
          severity: prev.severity,
          level: prev.level,
          title: truncate(prev.message),
          detail: prev.message,
          delta: "resolved",
        });
      }
    }
  }

  if (ambiguity?.issues) {
    for (let i = 0; i < ambiguity.issues.length; i++) {
      const issue = ambiguity.issues[i];
      out.push({
        id: `criteria-${i}`,
        source: "criteria",
        section: "Acceptance Criteria",
        severity: issue.severity,
        title: truncate(issue.missingCondition),
        detail: issue.missingCondition,
        criterionText: issue.criterionText,
        suggestedClause: issue.suggestedClause,
      });
    }
  }
  return out;
}

function groupBySection(findings: UnifiedFinding[]): [string, UnifiedFinding[]][] {
  const map = new Map<string, UnifiedFinding[]>();
  for (const f of findings) {
    const arr = map.get(f.section) || [];
    arr.push(f);
    map.set(f.section, arr);
  }
  return Array.from(map.entries());
}

/* ── Main panel ───────────────────────────────────────────────── */

export function IntelPanel({
  specPath,
  onOpenSpec,
  onApplyFix,
}: {
  specPath: string;
  onOpenSpec: (path: string) => void;
  onApplyFix?: (oldText: string, newText: string) => boolean;
}) {
  const [tab, setTab] = useState<IntelTab>("findings");

  // Restore intelTab from localStorage after hydration
  useEffect(() => {
    try {
      const saved = localStorage.getItem(INTEL_TAB_KEY);
      if (saved === "findings" || saved === "reference" || saved === "health") {
        setTab(saved);
      }
    } catch {}
  }, []);

  // Persist intelTab changes
  useEffect(() => {
    try { localStorage.setItem(INTEL_TAB_KEY, tab); } catch {}
  }, [tab]);

  const [selectedModel, setSelectedModel] = useState<string>("");
  const [analyzing, setAnalyzing] = useState(false);
  const [auditTriggered, setAuditTriggered] = useState(false);
  const cancelledRef = useRef(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  /* Fix flow state — keyed by finding ID */
  const [fixResults, setFixResults] = useState<Map<string, FixSuggestionResult>>(new Map());
  const [fixingId, setFixingId] = useState<string | null>(null);
  const [appliedFixes, setAppliedFixes] = useState<Set<string>>(new Set());
  const [fixErrors, setFixErrors] = useState<Map<string, string>>(new Map());

  /* ── Queries ── */
  const [lessonsResult] = useQuery<{ lessonsForSpec: Lesson[] }>({
    query: LESSONS_QUERY, variables: { path: specPath, limit: 5 },
  });
  const [conventionsResult] = useQuery<{ conventionsForSpec: Convention[] }>({
    query: CONVENTIONS_QUERY, variables: { path: specPath, limit: 8 },
  });
  const [csgResult] = useQuery<{ codebaseContext: CodebaseContext }>({
    query: CODEBASE_CONTEXT_QUERY, variables: { path: specPath },
  });
  const [relatedResult] = useQuery<{ relatedSpecs: SpecRelation[] }>({
    query: RELATED_SPECS_QUERY, variables: { path: specPath },
  });
  const [traceResult] = useQuery<{ specTraceability: SpecTraceability | null }>({
    query: SPEC_TRACEABILITY_QUERY, variables: { path: specPath },
  });
  const [healthResult] = useQuery<{ featureHealth: FeatureHealth | null }>({
    query: FEATURE_HEALTH_QUERY, variables: { path: specPath },
  });
  const [modelsResult] = useQuery<{
    availableModels: LLMModel[];
    unconfiguredProviders: UnconfiguredProvider[];
  }>({ query: AVAILABLE_MODELS_QUERY });

  /* ── Mutations ── */
  const [ambiguityResult, detectAmbiguities] = useMutation<
    { detectAmbiguities: AmbiguityReport | null },
    { path: string; model: string }
  >(DETECT_AMBIGUITIES_MUTATION);
  const [, suggestFix] = useMutation<
    { suggestFix: FixSuggestionResult | null },
    { specPath: string; sectionText: string; issueDescription: string; model: string }
  >(SUGGEST_FIX_MUTATION);
  const [, runAudit] = useMutation<
    { runAudit: AuditRunStatus },
    { path: string }
  >(RUN_AUDIT_MUTATION);

  /* ── Audit from disk ── */
  const [latestAuditResult, refetchLatestAudit] = useQuery<
    { latestAudit: SpeedAuditResult | null }
  >({
    query: LATEST_AUDIT_QUERY,
    variables: { specPath },
  });

  /* ── Audit running state (survives refresh) ── */
  const [auditStatusResult, refetchAuditStatus] = useQuery<
    { auditStatus: AuditStatus | null }
  >({
    query: AUDIT_STATUS_QUERY,
    variables: { specPath },
  });

  const serverAuditing = auditStatusResult.data?.auditStatus?.running ?? false;
  const auditing = auditTriggered || serverAuditing;
  const auditStartedAt = auditStatusResult.data?.auditStatus?.startedAt ?? null;

  /* Re-fetch audit data when a new audit file is written (by anyone) */
  useSubscription<{ auditCompleted: { feature: string; file: string } }>(
    { query: AUDIT_COMPLETED_SUBSCRIPTION, variables: {} },
    useCallback((_prev: unknown, _data: unknown) => {
      refetchLatestAudit({ requestPolicy: "network-only" });
      refetchAuditStatus({ requestPolicy: "network-only" });
      return _data;
    }, [refetchLatestAudit, refetchAuditStatus]),
  );

  /* ── Derived state ── */
  const models = modelsResult.data?.availableModels || [];
  if (!selectedModel && models.length > 0) setSelectedModel(models[0].id);

  const lessons = lessonsResult.data?.lessonsForSpec || [];
  const conventions = conventionsResult.data?.conventionsForSpec || [];
  const csg = csgResult.data?.codebaseContext;
  const related = relatedResult.data?.relatedSpecs || [];
  const trace = traceResult.data?.specTraceability;
  const health = healthResult.data?.featureHealth;
  const [recentAuditsResult] = useQuery<
    { recentAudits: SpeedAuditResult[] }
  >({
    query: RECENT_AUDITS_QUERY,
    variables: { specPath, limit: 3 },
  });

  const auditData = latestAuditResult.data?.latestAudit;
  const recentAudits = recentAuditsResult.data?.recentAudits ?? [];
  const previousAudit = recentAudits.length > 1 ? recentAudits[1] : null;
  const ambiguities = ambiguityResult.data?.detectAmbiguities;

  // Elapsed timer for running audits
  const [elapsed, setElapsed] = useState(0);
  const auditStartRef = useRef<number | null>(null);

  useEffect(() => {
    if (!auditing) {
      setElapsed(0);
      auditStartRef.current = null;
      return;
    }
    const start = auditStartedAt
      ? new Date(auditStartedAt).getTime()
      : Date.now();
    auditStartRef.current = start;
    setElapsed(Math.floor((Date.now() - start) / 1000));

    const interval = setInterval(() => {
      if (auditStartRef.current !== null) {
        setElapsed(Math.floor((Date.now() - auditStartRef.current) / 1000));
      }
    }, 1000);
    return () => clearInterval(interval);
  }, [auditing, auditStartedAt]);

  const findings = useMemo(() => buildFindings(auditData, previousAudit, ambiguities), [auditData, previousAudit, ambiguities]);
  const grouped = useMemo(() => groupBySection(findings), [findings]);

  const activeFindings = findings.filter(f => f.delta !== "resolved");
  const errorCount = activeFindings.filter(f => f.severity === "error" || f.severity === "critical").length;
  const warnCount = activeFindings.filter(f => f.severity === "warning" || f.severity === "major" || f.severity === "minor").length;
  const netChange = previousAudit
    ? (auditData?.issues?.length ?? 0) - (previousAudit.issues?.length ?? 0)
    : null;

  /* ── Handlers ── */
  const handleAudit = async () => {
    setAuditTriggered(true);
    await runAudit({ path: specPath });
    refetchLatestAudit({ requestPolicy: "network-only" });
    refetchAuditStatus({ requestPolicy: "network-only" });
    setAuditTriggered(false);
  };

  const handleAnalyze = async () => {
    if (analyzing || !selectedModel) return;
    cancelledRef.current = false;
    setAnalyzing(true);
    await detectAmbiguities({ path: specPath, model: selectedModel });
    if (!cancelledRef.current) setAnalyzing(false);
  };

  const handleFix = async (f: UnifiedFinding) => {
    if (!selectedModel) return;
    setFixingId(f.id);
    // For criteria findings, use the criterion text as section context.
    // For audit findings, use the section name + message as context.
    const sectionText = f.criterionText || f.section;
    const result = await suggestFix({
      specPath,
      sectionText,
      issueDescription: f.detail,
      model: selectedModel,
    });
    if (result.data?.suggestFix) {
      setFixResults(prev => new Map(prev).set(f.id, result.data!.suggestFix!));
    }
    setFixingId(null);
  };

  const handleApply = (f: UnifiedFinding) => {
    const fix = fixResults.get(f.id);
    if (!fix || !onApplyFix) return;
    if (onApplyFix(fix.oldText, fix.newText)) {
      setAppliedFixes(prev => new Set(prev).add(f.id));
      setFixErrors(prev => { const n = new Map(prev); n.delete(f.id); return n; });
    } else {
      setFixErrors(prev => new Map(prev).set(f.id, "Text not found in spec \u2014 content may have changed."));
    }
  };

  const handleUndo = (f: UnifiedFinding) => {
    const fix = fixResults.get(f.id);
    if (!fix || !onApplyFix) return;
    if (onApplyFix(fix.newText, fix.oldText)) {
      setAppliedFixes(prev => { const n = new Set(prev); n.delete(f.id); return n; });
    }
  };

  /* ── Render ── */
  return (
    <div className="intel-panel">
      <style>{`
        .intel-panel {
          display: flex;
          flex-direction: column;
          height: 100%;
          overflow: hidden;
          background: var(--color-bg-elevated);
        }

        /* ── Tab bar ── */
        .intel-tabs {
          display: flex;
          gap: 2px;
          padding: 8px 12px;
          border-bottom: 1px solid var(--color-border);
          flex-shrink: 0;
        }
        .intel-tab-btn {
          display: flex;
          align-items: center;
          gap: 5px;
          padding: 5px 10px;
          border: none;
          border-radius: 4px;
          cursor: pointer;
          font-family: var(--font-sans);
          font-size: 11px;
          font-weight: 500;
          transition: color 0.12s ease, background 0.12s ease;
        }
        .intel-tab-btn[data-active="true"] {
          color: var(--color-accent);
          background: rgba(0, 212, 170, 0.08);
        }
        .intel-tab-btn[data-active="false"] {
          color: var(--color-text-tertiary);
          background: transparent;
        }
        .intel-tab-btn:hover { background: rgba(255, 255, 255, 0.03); }
        .intel-tab-btn[data-active="true"]:hover { background: rgba(0, 212, 170, 0.08); }

        /* ── Scrollable content ── */
        .intel-content {
          flex: 1;
          overflow-y: auto;
          padding: 4px 0;
          scrollbar-width: thin;
          scrollbar-color: rgba(255,255,255,0.06) transparent;
        }
        .intel-content::-webkit-scrollbar { width: 4px; }
        .intel-content::-webkit-scrollbar-thumb {
          background: rgba(255,255,255,0.08);
          border-radius: 2px;
        }

        /* ── Sections (shared) ── */
        .intel-section { margin-bottom: 2px; }
        .intel-section-header {
          display: flex;
          align-items: center;
          gap: 6px;
          width: 100%;
          padding: 8px 12px;
          background: none;
          border: none;
          cursor: pointer;
          color: var(--color-text-tertiary);
          transition: background 0.12s ease;
        }
        .intel-section-header:hover { background: rgba(255, 255, 255, 0.02); }
        .intel-section-chevron {
          flex-shrink: 0;
          transition: transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
          color: var(--color-text-tertiary);
        }
        .intel-section-chevron[data-open="true"] { transform: rotate(90deg); }
        .intel-section-title {
          font-family: var(--font-mono);
          font-size: 10px;
          font-weight: 500;
          text-transform: uppercase;
          letter-spacing: 0.04em;
          flex: 1;
          text-align: left;
        }
        .intel-section-count {
          font-family: var(--font-mono);
          font-size: 10px;
          color: var(--color-text-tertiary);
          flex-shrink: 0;
        }
        .intel-section-body {
          display: grid;
          grid-template-rows: 0fr;
          transition: grid-template-rows 0.2s ease;
        }
        .intel-section-body[data-open="true"] { grid-template-rows: 1fr; }

        /* ── Cards (shared) ── */
        .intel-card {
          padding: 8px 12px;
          margin: 0 8px 4px;
          border-radius: 6px;
          border: 1px solid var(--color-border);
          background: var(--color-bg);
          transition: border-color 0.12s ease;
        }
        .intel-card:hover { border-color: rgba(255, 255, 255, 0.1); }
        .intel-card-title {
          font-family: var(--font-sans);
          font-size: 11px;
          font-weight: 500;
          color: var(--color-text);
          margin-bottom: 4px;
          line-height: 1.4;
        }
        .intel-card-body {
          font-family: var(--font-sans);
          font-size: 11px;
          color: var(--color-text-tertiary);
          line-height: 1.4;
        }
        .intel-card-meta {
          display: flex;
          gap: 8px;
          margin-top: 6px;
          font-family: var(--font-mono);
          font-size: 9px;
          color: var(--color-text-tertiary);
        }

        /* ── Relations (shared) ── */
        .intel-relation {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 5px 12px;
          margin: 0 8px;
          border-radius: 4px;
          cursor: pointer;
          transition: background 0.12s ease;
        }
        .intel-relation:hover { background: rgba(255, 255, 255, 0.03); }
        .intel-relation-type {
          font-family: var(--font-mono);
          font-size: 9px;
          font-weight: 500;
          text-transform: uppercase;
          flex-shrink: 0;
          min-width: 56px;
        }
        .intel-relation-path {
          font-family: var(--font-sans);
          font-size: 11px;
          color: var(--color-text-secondary);
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        /* ── Stats (shared) ── */
        .intel-stats {
          display: flex;
          gap: 12px;
          padding: 8px 12px;
          margin: 0 8px 8px;
          border-radius: 6px;
          background: var(--color-bg);
          border: 1px solid var(--color-border);
        }
        .intel-stat { display: flex; flex-direction: column; align-items: center; gap: 2px; }
        .intel-stat-value { font-family: var(--font-mono); font-size: 14px; font-weight: 600; color: var(--color-text); }
        .intel-stat-label { font-family: var(--font-mono); font-size: 9px; color: var(--color-text-tertiary); text-transform: uppercase; }

        .intel-empty {
          padding: 16px 12px;
          font-family: var(--font-sans);
          font-size: 11px;
          color: var(--color-text-tertiary);
          text-align: center;
        }

        /* ══════════════════════════════════════════════════════════
           Findings tab
           ══════════════════════════════════════════════════════════ */

        /* ── Verdict strip ── */
        .fv-verdict {
          padding: 10px 12px;
          border-bottom: 1px solid var(--color-border);
        }
        .fv-verdict-row {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .fv-verdict-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          flex-shrink: 0;
        }
        .fv-verdict-label {
          font-family: var(--font-mono);
          font-size: 11px;
          font-weight: 600;
          text-transform: uppercase;
        }
        .fv-verdict-counts {
          font-family: var(--font-mono);
          font-size: 10px;
          color: var(--color-text-tertiary);
          margin-left: auto;
        }
        .fv-verdict-summary {
          font-family: var(--font-sans);
          font-size: 10px;
          color: var(--color-text-tertiary);
          margin-top: 6px;
          line-height: 1.4;
        }

        /* ── Action bar ── */
        .fv-actions {
          display: flex;
          gap: 6px;
          padding: 8px 12px;
        }
        .fv-action-btn {
          flex: 1;
          padding: 7px 10px;
          border-radius: 6px;
          font-family: var(--font-sans);
          font-size: 11px;
          font-weight: 500;
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 5px;
          transition: background 0.12s ease, border-color 0.12s ease, opacity 0.12s ease;
        }
        .fv-action-btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .fv-action-default {
          background: var(--color-bg-card);
          color: var(--color-text);
          border: 1px solid var(--color-border);
        }
        .fv-action-primary {
          background: var(--color-accent);
          color: var(--color-bg);
          border: none;
        }
        .fv-action-cancel {
          flex: 0;
          padding: 7px 10px;
          border-radius: 6px;
          border: 1px solid var(--color-border);
          background: transparent;
          color: var(--color-text-secondary);
          font-family: var(--font-sans);
          font-size: 11px;
          font-weight: 500;
          cursor: pointer;
          transition: background 0.12s ease;
        }
        .fv-model-row {
          padding: 0 12px 8px;
          border-bottom: 1px solid var(--color-border);
        }
        .fv-model-select {
          width: 100%;
          padding: 4px 8px;
          background: var(--color-bg);
          color: var(--color-text-tertiary);
          border: 1px solid var(--color-border);
          border-radius: 4px;
          font-family: var(--font-mono);
          font-size: 10px;
          outline: none;
        }

        /* ── Findings list ── */
        .fv-counts {
          padding: 8px 12px 2px;
          font-family: var(--font-mono);
          font-size: 10px;
          color: var(--color-text-tertiary);
        }
        .fv-group-header {
          padding: 10px 12px 4px;
          font-family: var(--font-mono);
          font-size: 10px;
          font-weight: 500;
          color: var(--color-text-tertiary);
          text-transform: uppercase;
          letter-spacing: 0.04em;
          border-top: 1px solid rgba(255, 255, 255, 0.04);
          cursor: default;
        }

        /* ── Finding rows ── */
        .fv-row {
          display: flex;
          align-items: flex-start;
          gap: 6px;
          padding: 5px 12px;
          cursor: pointer;
          transition: background 0.12s ease;
          border-left: 2px solid transparent;
        }
        .fv-row:hover { background: rgba(255, 255, 255, 0.02); }
        .fv-row[data-expanded="true"] {
          background: rgba(255, 255, 255, 0.02);
          border-left-color: var(--color-accent);
        }
        .fv-sev {
          font-size: 11px;
          flex-shrink: 0;
          width: 14px;
          text-align: center;
          line-height: 1.45;
        }
        .fv-level {
          font-family: var(--font-mono);
          font-size: 9px;
          color: var(--color-text-tertiary);
          flex-shrink: 0;
          min-width: 16px;
        }
        .fv-title {
          flex: 1;
          font-family: var(--font-sans);
          font-size: 11px;
          color: var(--color-text-secondary);
          line-height: 1.45;
          overflow: hidden;
          text-overflow: ellipsis;
          display: -webkit-box;
          -webkit-line-clamp: 2;
          -webkit-box-orient: vertical;
        }
        .fv-source {
          font-family: var(--font-mono);
          font-size: 8px;
          color: var(--color-text-tertiary);
          text-transform: uppercase;
          flex-shrink: 0;
          opacity: 0.5;
          line-height: 1.45;
          padding-top: 1px;
        }

        /* ── Delta tags ── */
        .fv-delta {
          font-family: var(--font-mono);
          font-size: 8px;
          font-weight: 600;
          text-transform: uppercase;
          letter-spacing: 0.03em;
          padding: 1px 4px;
          border-radius: 2px;
          flex-shrink: 0;
          line-height: 1.4;
        }
        .fv-delta[data-delta="new"] {
          color: var(--color-accent);
          background: rgba(0, 212, 170, 0.1);
        }
        .fv-delta[data-delta="persistent"] {
          color: var(--color-text-tertiary);
        }
        .fv-delta[data-delta="resolved"] {
          color: var(--color-emerald);
          background: rgba(68, 204, 119, 0.08);
          text-decoration: line-through;
        }

        /* ── Verdict history dots ── */
        .fv-history-dots {
          display: flex;
          align-items: center;
          gap: 4px;
          margin-left: 8px;
        }
        .fv-history-dot {
          width: 6px;
          height: 6px;
          border-radius: 50%;
          opacity: 0.5;
        }
        .fv-history-dot:first-child { opacity: 1; }
        .fv-net-change {
          font-family: var(--font-mono);
          font-size: 10px;
          margin-left: auto;
        }

        /* ── Sizing card ── */
        .fv-sizing {
          margin: 8px 8px 4px;
          padding: 10px 12px;
          border-radius: 6px;
          border: 1px solid var(--color-border);
          background: var(--color-bg);
        }
        .fv-sizing-header {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-bottom: 6px;
        }
        .fv-sizing-tasks {
          font-family: var(--font-mono);
          font-size: 13px;
          font-weight: 600;
          color: var(--color-text);
        }
        .fv-sizing-rec {
          font-family: var(--font-mono);
          font-size: 9px;
          font-weight: 600;
          text-transform: uppercase;
          padding: 2px 6px;
          border-radius: 3px;
        }
        .fv-sizing-child {
          display: flex;
          align-items: baseline;
          gap: 6px;
          padding: 4px 0;
          font-family: var(--font-sans);
          font-size: 11px;
          color: var(--color-text-secondary);
        }
        .fv-sizing-child-arrow {
          color: var(--color-accent);
          font-family: var(--font-mono);
          font-size: 10px;
          flex-shrink: 0;
        }
        .fv-sizing-child-name {
          font-family: var(--font-mono);
          font-size: 11px;
          color: var(--color-text);
        }
        .fv-sizing-child-deps {
          font-family: var(--font-mono);
          font-size: 9px;
          color: var(--color-text-tertiary);
        }
        .fv-sizing-rationale {
          font-family: var(--font-sans);
          font-size: 10px;
          color: var(--color-text-tertiary);
          line-height: 1.5;
          margin-top: 8px;
        }

        /* ── Expanded detail ── */
        .fv-detail {
          padding: 4px 12px 10px 34px;
          animation: fvFadeIn 0.15s ease;
        }
        @keyframes fvFadeIn {
          from { opacity: 0; transform: translateY(-4px); }
          to { opacity: 1; transform: translateY(0); }
        }
        .fv-detail-msg {
          font-family: var(--font-sans);
          font-size: 11px;
          color: var(--color-text-secondary);
          line-height: 1.5;
          margin-bottom: 8px;
        }
        .fv-detail-criterion {
          font-family: var(--font-sans);
          font-size: 11px;
          color: var(--color-text-tertiary);
          line-height: 1.4;
          margin-bottom: 8px;
        }
        .fv-detail-criterion span {
          color: var(--color-text-tertiary);
          font-size: 10px;
        }
        .fv-suggested {
          padding: 6px 8px;
          background: rgba(0, 212, 170, 0.04);
          border-radius: 4px;
          border: 1px solid rgba(0, 212, 170, 0.1);
          margin-bottom: 8px;
        }
        .fv-suggested-label {
          font-family: var(--font-mono);
          font-size: 9px;
          color: var(--color-accent);
          margin-bottom: 2px;
          text-transform: uppercase;
        }
        .fv-suggested-text {
          font-family: var(--font-sans);
          font-size: 11px;
          color: var(--color-text-secondary);
        }

        /* ── Fix flow ── */
        .fv-fix-btn {
          padding: 4px 10px;
          border-radius: 4px;
          border: 1px solid var(--color-border);
          background: transparent;
          color: var(--color-text-secondary);
          font-family: var(--font-sans);
          font-size: 10px;
          font-weight: 500;
          cursor: pointer;
          display: inline-flex;
          align-items: center;
          gap: 4px;
          transition: background 0.12s ease, border-color 0.12s ease;
        }
        .fv-fix-btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .fv-diff-remove {
          padding: 6px 8px;
          border-radius: 4px;
          margin-bottom: 4px;
          background: rgba(239, 68, 100, 0.06);
          border: 1px solid rgba(239, 68, 100, 0.1);
        }
        .fv-diff-add {
          padding: 6px 8px;
          border-radius: 4px;
          margin-bottom: 6px;
          background: rgba(0, 212, 170, 0.06);
          border: 1px solid rgba(0, 212, 170, 0.1);
        }
        .fv-diff-label {
          font-family: var(--font-mono);
          font-size: 9px;
          margin-bottom: 2px;
        }
        .fv-diff-text {
          font-family: var(--font-sans);
          font-size: 11px;
        }
        .fv-apply-btn {
          padding: 5px 12px;
          border-radius: 4px;
          border: none;
          background: var(--color-accent);
          color: var(--color-bg);
          font-family: var(--font-sans);
          font-size: 11px;
          font-weight: 500;
          cursor: pointer;
          display: inline-flex;
          align-items: center;
          gap: 4px;
          transition: background 0.12s ease;
        }
        .fv-applied {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 6px 8px;
          border-radius: 4px;
          background: rgba(68, 204, 119, 0.06);
          border: 1px solid rgba(68, 204, 119, 0.15);
        }
        .fv-applied-label {
          display: flex;
          align-items: center;
          gap: 4px;
          font-family: var(--font-sans);
          font-size: 11px;
          font-weight: 500;
          color: var(--color-emerald);
        }
        .fv-undo-btn {
          padding: 3px 8px;
          border-radius: 3px;
          border: 1px solid var(--color-border);
          background: transparent;
          font-family: var(--font-sans);
          font-size: 10px;
          color: var(--color-text-tertiary);
          cursor: pointer;
          transition: background 0.12s ease;
        }
      `}</style>

      {/* ── Tab bar ── */}
      <div className="intel-tabs">
        <TabButton active={tab === "findings"} onClick={() => setTab("findings")} icon={Shield} label="Findings" />
        <TabButton active={tab === "reference"} onClick={() => setTab("reference")} icon={BookOpen} label="Reference" />
        <TabButton active={tab === "health"} onClick={() => setTab("health")} icon={Network} label="Health" />
      </div>

      <div className="intel-content">

        {/* ╔══════════════════════════════════════════════════════════
            ║ FINDINGS TAB
            ╚══════════════════════════════════════════════════════════ */}
        <div style={{ display: tab === "findings" ? "block" : "none" }}>
          <>
            {/* ── Verdict strip ── */}
            <div className="fv-verdict">
              {auditData ? (
                <>
                  <div className="fv-verdict-row">
                    <span
                      className="fv-verdict-dot"
                      style={{
                        background: auditData.status === "pass" ? "var(--color-emerald)"
                          : auditData.status === "fail" ? "var(--color-red)"
                          : "var(--color-amber)",
                      }}
                    />
                    <span
                      className="fv-verdict-label"
                      style={{
                        color: auditData.status === "pass" ? "var(--color-emerald)"
                          : auditData.status === "fail" ? "var(--color-red)"
                          : "var(--color-amber)",
                      }}
                    >
                      {auditData.status}
                    </span>
                    {/* History dots */}
                    {recentAudits.length > 1 && (
                      <span className="fv-history-dots">
                        {recentAudits.slice(0, 3).map((a, i) => (
                          <span
                            key={i}
                            className="fv-history-dot"
                            title={a.ranAt ? new Date(a.ranAt).toLocaleString() : ""}
                            style={{
                              background: a.status === "pass" ? "var(--color-emerald)"
                                : a.status === "fail" ? "var(--color-red)"
                                : "var(--color-amber)",
                            }}
                          />
                        ))}
                      </span>
                    )}
                    {/* Net change */}
                    {netChange !== null && (
                      <span
                        className="fv-net-change"
                        style={{
                          color: netChange > 0 ? "var(--color-red)"
                            : netChange < 0 ? "var(--color-emerald)"
                            : "var(--color-text-tertiary)",
                        }}
                      >
                        {netChange > 0 ? `+${netChange}` : netChange === 0 ? "±0" : `${netChange}`}
                      </span>
                    )}
                  </div>
                  {auditData.stale && (
                    <div className="fv-verdict-summary" style={{ color: "var(--color-amber)" }}>
                      Spec changed since this audit ran
                    </div>
                  )}
                </>
              ) : (
                <div style={{
                  fontFamily: "var(--font-sans)", fontSize: 11,
                  color: "var(--color-text-tertiary)",
                }}>
                  {latestAuditResult.error
                    ? <span style={{ color: "var(--color-red)" }}>Audit query error: {latestAuditResult.error.message}</span>
                    : latestAuditResult.fetching
                      ? "Loading audit..."
                      : "No audit results yet"}
                </div>
              )}
              {ambiguities && (
                <div className="fv-verdict-summary" style={{ marginTop: auditData ? 6 : 0 }}>
                  {ambiguities.summary}
                </div>
              )}
            </div>

            {/* ── Action bar ── */}
            <div className="fv-actions">
              <button
                className="fv-action-btn fv-action-default"
                onClick={handleAudit}
                disabled={auditing}
              >
                {auditing ? (
                  <>
                    <Loader2 size={12} className="animate-spin" />
                    <span>Running audit&hellip;</span>
                    <span style={{
                      fontFamily: "var(--font-mono)", fontSize: 10,
                      color: "var(--color-text-tertiary)", marginLeft: "auto",
                    }}>
                      {elapsed}s
                    </span>
                  </>
                ) : (
                  <>Run Audit</>
                )}
              </button>
              <button
                className="fv-action-btn fv-action-primary"
                onClick={handleAnalyze}
                disabled={!selectedModel || analyzing}
              >
                {analyzing ? (
                  <><Loader2 size={12} className="animate-spin" /> Analyzing&hellip;</>
                ) : (
                  <><Sparkles size={12} /> Analyze</>
                )}
              </button>
              {analyzing && (
                <button
                  className="fv-action-cancel"
                  onClick={() => { cancelledRef.current = true; setAnalyzing(false); }}
                >
                  Cancel
                </button>
              )}
            </div>

            {/* ── Model selector (compact) ── */}
            <div className="fv-model-row">
              <select
                className="fv-model-select"
                value={selectedModel}
                onChange={(e) => setSelectedModel(e.target.value)}
              >
                {models.length === 0 && <option value="">No models available</option>}
                {models.map((m) => (
                  <option key={m.id} value={m.id}>{m.label}</option>
                ))}
              </select>
            </div>

            {/* ── Findings list ── */}
            {findings.length > 0 && (
              <>
                <div className="fv-counts">
                  {errorCount > 0 && (
                    <span style={{ color: "var(--color-red)" }}>{errorCount} error{errorCount !== 1 ? "s" : ""}</span>
                  )}
                  {errorCount > 0 && warnCount > 0 && <span> &middot; </span>}
                  {warnCount > 0 && (
                    <span style={{ color: "var(--color-amber)" }}>{warnCount} warning{warnCount !== 1 ? "s" : ""}</span>
                  )}
                </div>

                {grouped.map(([section, items]) => (
                  <div key={section}>
                    <div className="fv-group-header">{section}</div>
                    {items.map((f) => (
                      <div key={f.id}>
                        {/* Row */}
                        <div
                          className="fv-row"
                          data-expanded={expandedId === f.id ? "true" : "false"}
                          onClick={() => setExpandedId(expandedId === f.id ? null : f.id)}
                        >
                          <span className="fv-sev" style={{ color: severityColor(f.severity) }}>
                            {severityIcon(f.severity)}
                          </span>
                          {f.level != null && <span className="fv-level">L{f.level}</span>}
                          <span className="fv-title">{f.delta === "resolved" ? <s>{f.title}</s> : f.title}</span>
                          {f.delta && <span className="fv-delta" data-delta={f.delta}>{f.delta}</span>}
                          <span className="fv-source">{f.source}</span>
                        </div>

                        {/* Expanded detail */}
                        {expandedId === f.id && (
                          <div className="fv-detail">
                            <div className="fv-detail-msg">{f.detail}</div>

                            {f.criterionText && (
                              <div className="fv-detail-criterion">
                                <span>Criterion: </span>
                                {f.criterionText}
                              </div>
                            )}

                            {f.suggestedClause && (
                              <div className="fv-suggested">
                                <div className="fv-suggested-label">Suggested addition</div>
                                <div className="fv-suggested-text">{f.suggestedClause}</div>
                              </div>
                            )}

                            {/* Fix flow — all findings (audit + criteria) */}
                            {f.delta !== "resolved" && (
                              <>
                                {fixResults.has(f.id) ? (
                                  appliedFixes.has(f.id) ? (
                                    <div className="fv-applied">
                                      <span className="fv-applied-label">
                                        <Check size={11} /> Applied
                                      </span>
                                      {onApplyFix && (
                                        <button className="fv-undo-btn" onClick={(e) => { e.stopPropagation(); handleUndo(f); }}>
                                          Undo
                                        </button>
                                      )}
                                    </div>
                                  ) : (
                                    <>
                                      <div className="fv-diff-remove">
                                        <div className="fv-diff-label" style={{ color: "var(--color-red)" }}>REMOVE</div>
                                        <div className="fv-diff-text" style={{ color: "var(--color-text-tertiary)", textDecoration: "line-through" }}>
                                          {fixResults.get(f.id)!.oldText}
                                        </div>
                                      </div>
                                      <div className="fv-diff-add">
                                        <div className="fv-diff-label" style={{ color: "var(--color-accent)" }}>REPLACE WITH</div>
                                        <div className="fv-diff-text" style={{ color: "var(--color-text-secondary)" }}>
                                          {fixResults.get(f.id)!.newText}
                                        </div>
                                      </div>
                                      <div style={{
                                        fontFamily: "var(--font-sans)", fontSize: 10,
                                        color: "var(--color-text-tertiary)", marginBottom: 6,
                                      }}>
                                        {fixResults.get(f.id)!.rationale}
                                      </div>
                                      {fixErrors.has(f.id) && (
                                        <div style={{
                                          fontFamily: "var(--font-sans)", fontSize: 10,
                                          color: "var(--color-red)", marginBottom: 6,
                                        }}>
                                          {fixErrors.get(f.id)}
                                        </div>
                                      )}
                                      {onApplyFix && (
                                        <button className="fv-apply-btn" onClick={(e) => { e.stopPropagation(); handleApply(f); }}>
                                          <Check size={11} /> Apply Fix
                                        </button>
                                      )}
                                    </>
                                  )
                                ) : (
                                  <button
                                    className="fv-fix-btn"
                                    disabled={fixingId === f.id}
                                    onClick={(e) => { e.stopPropagation(); handleFix(f); }}
                                  >
                                    {fixingId === f.id ? (
                                      <><Loader2 size={10} className="animate-spin" /> Generating fix&hellip;</>
                                    ) : (
                                      <><Wand2 size={10} /> Fix this</>
                                    )}
                                  </button>
                                )}
                              </>
                            )}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                ))}
              </>
            )}

            {/* ── Sizing card ── */}
            {auditData?.sizing && auditData.sizing.recommendation !== "ok" && (
              <div className="fv-sizing">
                <div className="fv-sizing-header">
                  <span className="fv-sizing-tasks">{auditData.sizing.estimatedTasks} tasks</span>
                  <span
                    className="fv-sizing-rec"
                    style={{
                      color: auditData.sizing.recommendation === "multi_rfc" ? "var(--color-red)" : "var(--color-amber)",
                      background: auditData.sizing.recommendation === "multi_rfc"
                        ? "rgba(239, 68, 100, 0.1)"
                        : "rgba(240, 178, 50, 0.1)",
                    }}
                  >
                    {auditData.sizing.recommendation}
                  </span>
                </div>
                {auditData.sizing.suggestedChildren.length > 0 && (
                  <div>
                    {auditData.sizing.suggestedChildren.map((child, i) => (
                      <div key={i} className="fv-sizing-child">
                        <span className="fv-sizing-child-arrow">&rarr;</span>
                        <div>
                          <div className="fv-sizing-child-name">{child.name}</div>
                          {child.dependsOn.length > 0 && (
                            <div className="fv-sizing-child-deps">
                              depends on: {child.dependsOn.join(", ")}
                            </div>
                          )}
                          {child.testableOutput && (
                            <div style={{ fontFamily: "var(--font-sans)", fontSize: 10, color: "var(--color-text-tertiary)", marginTop: 2 }}>
                              {child.testableOutput.slice(0, 120)}
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                {auditData.sizing.rationale && (
                  <details>
                    <summary style={{
                      fontFamily: "var(--font-mono)", fontSize: 9, color: "var(--color-text-tertiary)",
                      cursor: "pointer", marginTop: 6,
                    }}>
                      Rationale
                    </summary>
                    <div className="fv-sizing-rationale">{auditData.sizing.rationale}</div>
                  </details>
                )}
              </div>
            )}

            {findings.length === 0 && !auditing && !analyzing && (
              <div className="intel-empty">
                Run an audit or analyze criteria to find issues
              </div>
            )}
          </>
        </div>

        {/* ╔══════════════════════════════════════════════════════════
           ║ REFERENCE TAB
           ╚══════════════════════════════════════════════════════════ */}
        <div style={{ display: tab === "reference" ? "block" : "none" }}>
          <>
            {/* CSG Stats */}
            {csg && csg.stats.clusters > 0 && (
              <Section title="Codebase" count={csg.stats.clusters} defaultOpen>
                <div className="intel-stats">
                  <div className="intel-stat" title="Groups of tightly-coupled code modules referenced by this spec">
                    <span className="intel-stat-value">{csg.stats.clusters}</span>
                    <span className="intel-stat-label">clusters</span>
                  </div>
                  <div className="intel-stat" title="Source files in the codebase that this spec's scope touches">
                    <span className="intel-stat-value">{csg.stats.files}</span>
                    <span className="intel-stat-label">files</span>
                  </div>
                  <div className="intel-stat">
                    <span className="intel-stat-value">{csg.stats.nodes}</span>
                    <span className="intel-stat-label">symbols</span>
                  </div>
                  <div className="intel-stat" style={{ marginLeft: "auto" }}>
                    <span className="intel-stat-value" style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
                      of {csg.stats.totalNodes}
                    </span>
                    <span className="intel-stat-label">total</span>
                  </div>
                </div>
                {csg.clusters.map((cl) => (
                  <div key={cl.id} className="intel-card">
                    <div className="intel-card-title">{cl.label}</div>
                    <div className="intel-card-meta">
                      <span>{cl.fileCount} files</span>
                      <span>{cl.symbolCount} symbols</span>
                      <span>cohesion {(cl.cohesion * 100).toFixed(0)}%</span>
                    </div>
                  </div>
                ))}
              </Section>
            )}

            {/* Conventions */}
            <Section title="Conventions" count={conventions.length}>
              {conventions.length === 0 ? (
                <div className="intel-empty">No matching conventions</div>
              ) : (
                conventions.map((c) => {
                  const files = c.convention.match(/`([^`]+)`/g)?.map((f: string) => f.replace(/`/g, "")) || [];
                  const shortFiles = files.map((f: string) => f.split("/").pop() || f);
                  const commitMatch = c.convention.match(/(\d+)\/(\d+) commits/);
                  return (
                    <div key={c.id} className="intel-card">
                      {files.length >= 2 ? (
                        <>
                          <div className="intel-card-title" style={{ fontSize: 10, color: "var(--color-text-tertiary)", marginBottom: 6 }}>
                            These files change together
                          </div>
                          <div style={{ display: "flex", flexDirection: "column", gap: 3, marginBottom: 6 }}>
                            {shortFiles.map((f: string, i: number) => (
                              <div key={i} style={{
                                fontFamily: "var(--font-mono)", fontSize: 11,
                                color: "var(--color-accent)",
                                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                              }} title={files[i]}>
                                {f}
                              </div>
                            ))}
                          </div>
                          <div className="intel-card-meta">
                            {commitMatch && <span>{commitMatch[1]}/{commitMatch[2]} commits</span>}
                            <span>{(c.adherence * 100).toFixed(0)}% adherence</span>
                            <span style={{ marginLeft: "auto", fontStyle: "italic" }}>
                              If your spec touches one, scope should include both
                            </span>
                          </div>
                        </>
                      ) : (
                        <>
                          <div className="intel-card-body">{c.convention}</div>
                          <div className="intel-card-meta">
                            {c.tags.map((t: string) => <span key={t}>{t}</span>)}
                            <span style={{ marginLeft: "auto" }}>{(c.adherence * 100).toFixed(0)}% adherence</span>
                          </div>
                        </>
                      )}
                    </div>
                  );
                })
              )}
            </Section>

            {/* Lessons */}
            <Section title="Lessons" count={lessons.length}>
              {lessons.length === 0 ? (
                <div className="intel-empty">No relevant lessons</div>
              ) : (
                lessons.map((l) => (
                  <div key={l.id} className="intel-card">
                    <div className="intel-card-title">{l.observationType || "observation"}</div>
                    <div className="intel-card-body">
                      {typeof l.detail === "string"
                        ? l.detail.slice(0, 200)
                        : JSON.stringify(l.detail).slice(0, 200)}
                    </div>
                    <div className="intel-card-meta">
                      <span>{l.feature}</span>
                      <span>{l.stage}</span>
                    </div>
                  </div>
                ))
              )}
            </Section>

            {/* Related specs */}
            {related.length > 0 && (
              <>
                <Section title="Dependencies" count={related.filter(r => r.relType === "depends_on").length} defaultOpen>
                  {related.filter(r => r.relType === "depends_on").length === 0 ? (
                    <div className="intel-empty">No dependencies</div>
                  ) : (
                    related.filter(r => r.relType === "depends_on").map((r, i) => {
                      const target = r.source === specPath ? r.target : r.source;
                      const direction = r.source === specPath ? "\u2192" : "\u2190";
                      return (
                        <div key={`dep-${i}`} className="intel-relation" onClick={() => onOpenSpec(target)}>
                          <span className="intel-relation-type" style={{ color: "var(--color-amber)" }}>
                            {direction} dep
                          </span>
                          <SpecLabel path={target} />
                        </div>
                      );
                    })
                  )}
                </Section>

                {related.some(r => r.relType === "see") && (
                  <Section title="See Also" count={related.filter(r => r.relType === "see").length}>
                    {related.filter(r => r.relType === "see").map((r, i) => {
                      const target = r.source === specPath ? r.target : r.source;
                      return (
                        <div key={`see-${i}`} className="intel-relation" onClick={() => onOpenSpec(target)}>
                          <span className="intel-relation-type" style={{ color: "var(--color-accent)" }}>see</span>
                          <SpecLabel path={target} />
                        </div>
                      );
                    })}
                  </Section>
                )}

                {related.some(r => r.relType === "shared_infra") && (
                  <Section title="Shared Infrastructure" count={related.filter(r => r.relType === "shared_infra").length}>
                    {related.filter(r => r.relType === "shared_infra").map((r, i) => {
                      const target = r.source === specPath ? r.target : r.source;
                      return (
                        <div key={`infra-${i}`} className="intel-relation" onClick={() => onOpenSpec(target)}>
                          <span className="intel-relation-type" style={{ color: "var(--color-violet)" }}>shared</span>
                          <SpecLabel path={target} />
                        </div>
                      );
                    })}
                  </Section>
                )}

                {related.some(r => r.relType === "parent_rfc") && (
                  <Section title="Parent RFC" defaultOpen>
                    {related.filter(r => r.relType === "parent_rfc").map((r, i) => {
                      const target = r.source === specPath ? r.target : r.source;
                      return (
                        <div key={`parent-${i}`} className="intel-relation" onClick={() => onOpenSpec(target)}>
                          <span className="intel-relation-type" style={{ color: "var(--color-rose)" }}>parent</span>
                          <SpecLabel path={target} />
                        </div>
                      );
                    })}
                  </Section>
                )}
              </>
            )}
          </>
        </div>

        {/* ╔══════════════════════════════════════════════════════════
           ║ HEALTH TAB
           ╚══════════════════════════════════════════════════════════ */}
        <div style={{ display: tab === "health" ? "block" : "none" }}>
          <>
            {/* Traceability */}
            {trace && (
              <Section title="Traceability" defaultOpen>
                <div
                  style={{ padding: "4px 12px 8px" }}
                  title={`${trace.covered.length} of ${trace.requirementsFound} spec requirements have matching implementation evidence`}
                >
                  <div style={{
                    display: "flex", justifyContent: "space-between", marginBottom: 4,
                    fontFamily: "var(--font-mono)", fontSize: 11,
                  }}>
                    <span style={{ color: "var(--color-text-secondary)" }}>
                      {trace.covered.length} of {trace.requirementsFound} requirements implemented
                    </span>
                    <span style={{
                      fontWeight: 600,
                      color: trace.coverageRatio >= 0.8 ? "var(--color-emerald)"
                        : trace.coverageRatio >= 0.5 ? "var(--color-amber)"
                        : "var(--color-red)",
                    }}>
                      {Math.round(trace.coverageRatio * 100)}%
                    </span>
                  </div>
                  <div style={{
                    height: 4, borderRadius: 2, background: "var(--color-bg-card)", overflow: "hidden",
                  }}>
                    <div style={{
                      height: "100%", borderRadius: 2,
                      width: `${Math.round(trace.coverageRatio * 100)}%`,
                      background: trace.coverageRatio >= 0.8 ? "var(--color-emerald)"
                        : trace.coverageRatio >= 0.5 ? "var(--color-amber)"
                        : "var(--color-red)",
                      transition: "width 0.3s ease",
                    }} />
                  </div>
                </div>
                {trace.uncovered.length > 0 && (
                  <div style={{ padding: "0 8px 8px" }}>
                    {trace.uncovered.map((r, i) => (
                      <div key={i} className="intel-card" style={{ borderColor: "rgba(239, 68, 100, 0.2)" }}>
                        <div className="intel-card-body" style={{ color: "var(--color-red)" }}>
                          {typeof r === "string" ? r.slice(0, 150) : JSON.stringify(r).slice(0, 150)}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </Section>
            )}

            {/* Observation summary */}
            {health?.observationSummary && (
              <Section title="Observations" count={health.observationSummary.total} defaultOpen>
                <div style={{ padding: "0 8px 8px", display: "flex", flexWrap: "wrap", gap: 4 }}>
                  {health.observationSummary.types.map((t) => (
                    <div key={t.type} style={{
                      display: "flex", alignItems: "center", gap: 6,
                      padding: "4px 8px", borderRadius: 4,
                      background: "var(--color-bg)", border: "1px solid var(--color-border)",
                      fontFamily: "var(--font-sans)", fontSize: 11,
                    }}>
                      <span style={{
                        fontFamily: "var(--font-mono)", fontSize: 12, fontWeight: 600,
                        color: t.type === "retry" || t.type === "security_finding"
                          ? "var(--color-red)"
                          : t.type === "success"
                            ? "var(--color-emerald)"
                            : t.type === "human_override"
                              ? "var(--color-amber)"
                              : "var(--color-text)",
                      }}>
                        {t.count}
                      </span>
                      <span style={{ color: "var(--color-text-secondary)" }}>
                        {t.type.replace(/_/g, " ")}
                      </span>
                    </div>
                  ))}
                </div>
              </Section>
            )}

            {/* Tasks */}
            {health && health.tasks.length > 0 && (
              <Section title="Tasks" count={health.tasks.length}>
                <div style={{ padding: "0 8px 8px" }}>
                  {health.tasks.map((t) => (
                    <div key={t.id} style={{
                      display: "flex", alignItems: "center", gap: 6,
                      padding: "4px 8px", borderRadius: 4, marginBottom: 2,
                    }}>
                      <span style={{
                        width: 6, height: 6, borderRadius: "50%", flexShrink: 0,
                        background: t.status === "done" ? "var(--color-emerald)"
                          : t.status === "failed" ? "var(--color-red)"
                          : t.status === "blocked" ? "var(--color-amber)"
                          : "var(--color-text-tertiary)",
                      }} />
                      <span style={{
                        flex: 1, fontFamily: "var(--font-sans)", fontSize: 11,
                        color: "var(--color-text-secondary)",
                        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                      }}>
                        {t.title}
                      </span>
                      {t.retryCount > 0 && (
                        <span style={{
                          fontFamily: "var(--font-mono)", fontSize: 9, color: "var(--color-amber)", flexShrink: 0,
                        }}>
                          {t.retryCount}&times;
                        </span>
                      )}
                      <span style={{
                        fontFamily: "var(--font-mono)", fontSize: 9, color: "var(--color-text-tertiary)", flexShrink: 0,
                      }}>
                        {t.filesTouched}f
                      </span>
                    </div>
                  ))}
                </div>
              </Section>
            )}

            {/* Highlights */}
            {health && health.highlights.length > 0 && (
              <Section title="Highlights" count={health.highlights.length}>
                {health.highlights.map((h, i) => (
                  <div key={i} className="intel-card">
                    <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
                      <span style={{
                        fontFamily: "var(--font-mono)", fontSize: 9, fontWeight: 600, textTransform: "uppercase",
                        color: h.type === "security_finding" ? "var(--color-red)"
                          : h.type === "human_override" ? "var(--color-amber)"
                          : h.type === "context_miss" ? "var(--color-violet)"
                          : "var(--color-text-tertiary)",
                      }}>
                        {h.type.replace(/_/g, " ")}
                      </span>
                      <span style={{
                        fontFamily: "var(--font-mono)", fontSize: 9, color: "var(--color-text-tertiary)",
                      }}>
                        {h.stage}
                      </span>
                    </div>
                    <div className="intel-card-body">{h.detail}</div>
                  </div>
                ))}
              </Section>
            )}

            {/* Contract entities */}
            {health && health.contractEntities.length > 0 && (
              <Section title="Contract" count={health.contractEntities.length}>
                <div style={{ padding: "0 8px 8px" }}>
                  {health.contractEntities.map((e, i) => (
                    <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, padding: "3px 12px" }}>
                      <span style={{
                        fontFamily: "var(--font-mono)", fontSize: 9, fontWeight: 500,
                        color: "var(--color-text-tertiary)", textTransform: "uppercase",
                        minWidth: 48, flexShrink: 0,
                      }}>
                        {e.type}
                      </span>
                      <span style={{
                        fontFamily: "var(--font-sans)", fontSize: 11, color: "var(--color-text-secondary)",
                        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                      }}>
                        {e.name}
                      </span>
                    </div>
                  ))}
                </div>
              </Section>
            )}

            {!trace && !health?.observationSummary && (
              <div className="intel-empty">No health data for this feature</div>
            )}
          </>
        </div>
      </div>
    </div>
  );
}
