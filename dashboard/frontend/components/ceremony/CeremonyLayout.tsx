"use client";

import React, {
  useState,
  useCallback,
  useRef,
  useEffect,
  useMemo,
} from "react";
import { useQuery, useMutation, useSubscription } from "urql";
import { Eye, Pencil, MessageCircle } from "lucide-react";
import { SpecEditor, type SpecEditorHandle, type EditorSelection } from "@/components/editor/SpecEditor";
import { SpecPreview } from "@/components/editor/SpecPreview";
import { ContextPanel } from "./ContextPanel";
import { ValidationGutter } from "./ValidationGutter";
import { SuggestionSidebar } from "./SuggestionSidebar";
import { CommitBar } from "./CommitBar";
import { CommitDialog } from "./CommitDialog";
import { ContributorBanner } from "./ContributorBanner";
import { DecompositionPanel } from "./DecompositionPanel";
import { TaskBoard } from "./TaskBoard";
import type { ContextPackage, SpecDraft, ValidationIssue } from "@/lib/graphql/queries/ceremony";
import {
  CEREMONY_INFO_QUERY,
  CURRENT_ACTOR_QUERY,
  type CeremonyInfoData,
  type CurrentActorData,
} from "@/lib/graphql/queries/ceremony";
import {
  COMMIT_SPEC_MUTATION,
  CEREMONY_PROGRESS_QUERY,
  CLAIM_SPEC_MUTATION,
  RELEASE_SPEC_MUTATION,
  SUBMIT_RATIFICATION_MUTATION,
  type CommitSpecData,
  type CommitSpecVars,
  type CeremonyProgressData,
  type CeremonyProgressVars,
  type ClaimSpecData,
  type ClaimSpecVars,
  type ReleaseSpecData,
  type ReleaseSpecVars,
  type SpecClaimInfo,
  type SpecProgressInfo,
  type SubmitRatificationData,
  type SubmitRatificationVars,
} from "@/lib/graphql/queries/ceremony-commitment";
import {
  TabClaimBadge,
  ProgressOverview,
  ReadOnlyBanner,
  SuggestionPopover,
  type ClaimState,
  type ProgressRowData,
} from "./ownership";
import {
  DECOMPOSE_DRAFT_MUTATION,
  DECOMPOSITION_RESULT_QUERY,
  DECOMPOSITION_PROGRESS_SUBSCRIPTION,
  GENERATE_CHILD_RFCS_MUTATION,
  type DecomposeDraftData,
  type DecomposeDraftVars,
  type DecompositionResultData,
  type DecompositionResult,
  type GenerateChildRfcsData,
  type GenerateChildRfcsVars,
  type DecompositionProgressData,
} from "@/lib/graphql/queries/ceremony-editor";
import {
  SUGGESTIONS_QUERY,
  CREATE_SUGGESTION_MUTATION,
  RESOLVE_SUGGESTION_MUTATION,
  REPLY_SUGGESTION_MUTATION,
  type SuggestionsData,
  type SuggestionsVars,
  type CreateSuggestionData,
  type CreateSuggestionVars,
  type ResolveSuggestionData,
  type ResolveSuggestionVars,
  type ReplySuggestionData,
  type ReplySuggestionVars,
} from "@/lib/graphql/queries/ceremony-suggestions";
import {
  CEREMONY_MODELS_QUERY,
} from "@/lib/graphql/queries/editor";
import {
  ALL_SPEC_DRAFTS_QUERY,
  VALIDATION_STATE_QUERY,
  GENERATE_DRAFT_MUTATION,
  UPDATE_DRAFT_MUTATION,
  VALIDATE_DRAFT_MUTATION,
  DRAFT_GENERATION_PROGRESS_SUBSCRIPTION,
  type AllSpecDraftsData,
  type AllSpecDraftsVars,
  type ValidationStateData,
  type ValidationStateVars,
  type GenerateDraftData,
  type GenerateDraftVars,
  type UpdateDraftData,
  type UpdateDraftVars,
  type ValidateDraftData,
  type ValidateDraftVars,
  type DraftGenerationProgressData,
} from "@/lib/graphql/queries/ceremony-editor";

// ── Types ─────────────────────────────────────────────────────

interface CeremonyLayoutProps {
  featureName: string;
  contextPackage: ContextPackage;
  onRefine: (text: string) => void;
  refining: boolean;
}

interface LLMModel {
  id: string;
  provider: string;
  label: string;
}

type SpecType = string;

const CORE_TABS: { type: string; label: string }[] = [
  { type: "prd", label: "PRD" },
  { type: "design", label: "Design" },
  { type: "rfc", label: "RFC" },
];

// PRD → Design → RFC: each requires the previous
const REQUIRES: Record<string, string | null> = {
  prd: null,
  design: "prd",
  rfc: "design",
};

function tabLabel(specType: string): string {
  if (specType === "prd") return "PRD";
  if (specType === "design") return "Design";
  if (specType === "rfc") return "RFC";
  // Child RFC: "rfc-ingestion" → "RFC: ingestion"
  if (specType.startsWith("rfc-")) {
    const suffix = specType.slice(4).replace(/-/g, " ");
    return `RFC: ${suffix}`;
  }
  return specType.toUpperCase();
}

// ── Component ─────────────────────────────────────────────────

export function CeremonyLayout({
  featureName,
  contextPackage,
  onRefine,
  refining,
}: CeremonyLayoutProps) {
  // ── State ────────────────────────────────────────────────────
  const [activeTab, setActiveTab] = useState<SpecType>("prd");
  const [drafts, setDrafts] = useState<Record<string, SpecDraft>>({});
  const [editContent, setEditContent] = useState<Record<string, string>>({});
  const [generating, setGenerating] = useState(false);
  const [genElapsed, setGenElapsed] = useState(0);
  const [genError, setGenError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [mode, setMode] = useState<"edit" | "preview">("edit");
  const [gutterExpanded, setGutterExpanded] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [commitDialogOpen, setCommitDialogOpen] = useState(false);
  const [committing, setCommitting] = useState(false);
  const [commitError, setCommitError] = useState<string | null>(null);
  const [decomposing, setDecomposing] = useState(false);
  const [decomposeElapsed, setDecomposeElapsed] = useState(0);
  const decomposeTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [decompositionResult, setDecompositionResult] = useState<DecompositionResult | null>(null);
  const [decomposeStage, setDecomposeStage] = useState<string>("loading_specs");
  const [decomposeError, setDecomposeError] = useState<string | null>(null);
  const [showTaskBoard, setShowTaskBoard] = useState(false);
  const [validating, setValidating] = useState(false);
  const [lastEditTime, setLastEditTime] = useState(0);
  const [refinement, setRefinement] = useState("");

  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const genTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const editorRef = useRef<SpecEditorHandle>(null);

  // ── GraphQL ──────────────────────────────────────────────────

  const [{ data: draftsData }, reexecuteDrafts] = useQuery<AllSpecDraftsData, AllSpecDraftsVars>({
    query: ALL_SPEC_DRAFTS_QUERY,
    variables: { featureName },
  });

  const [{ data: vsData }, reexecuteVs] = useQuery<ValidationStateData, ValidationStateVars>({
    query: VALIDATION_STATE_QUERY,
    variables: { featureName, specType: activeTab },
  });

  const [{ data: modelsData }] = useQuery<{ ceremonyModels: LLMModel[] }>({
    query: CEREMONY_MODELS_QUERY,
  });

  const [, executeGenerate] = useMutation<GenerateDraftData, GenerateDraftVars>(GENERATE_DRAFT_MUTATION);
  const [, executeUpdate] = useMutation<UpdateDraftData, UpdateDraftVars>(UPDATE_DRAFT_MUTATION);
  const [, executeValidate] = useMutation<ValidateDraftData, ValidateDraftVars>(VALIDATE_DRAFT_MUTATION);

  // Suggestions
  const [{ data: suggestionsData }, reexecuteSuggestions] = useQuery<SuggestionsData, SuggestionsVars>({
    query: SUGGESTIONS_QUERY,
    variables: { featureName },
  });
  const [, executeCreateSuggestion] = useMutation<CreateSuggestionData, CreateSuggestionVars>(CREATE_SUGGESTION_MUTATION);
  const [, executeCommitSpec] = useMutation<CommitSpecData, CommitSpecVars>(COMMIT_SPEC_MUTATION);
  const [, executeDecompose] = useMutation<DecomposeDraftData, DecomposeDraftVars>(DECOMPOSE_DRAFT_MUTATION);
  const [, executeGenerateChildRfcs] = useMutation<GenerateChildRfcsData, GenerateChildRfcsVars>(GENERATE_CHILD_RFCS_MUTATION);
  const [, executeResolveSuggestion] = useMutation<ResolveSuggestionData, ResolveSuggestionVars>(RESOLVE_SUGGESTION_MUTATION);
  const [, executeReplySuggestion] = useMutation<ReplySuggestionData, ReplySuggestionVars>(REPLY_SUGGESTION_MUTATION);

  // Per-spec progress query — one batched round trip that returns
  // claim + commit + ratification state for every drafted spec.
  // Refetched on every mutation that could change ownership or progress
  // (claim, release, commit, ratify) so tab chrome stays in sync.
  const [{ data: progressData }, reexecuteProgress] = useQuery<CeremonyProgressData, CeremonyProgressVars>({
    query: CEREMONY_PROGRESS_QUERY,
    variables: { featureName },
  });
  const [, executeClaimSpec] = useMutation<ClaimSpecData, ClaimSpecVars>(CLAIM_SPEC_MUTATION);
  const [, executeReleaseSpec] = useMutation<ReleaseSpecData, ReleaseSpecVars>(RELEASE_SPEC_MUTATION);
  const [, executeSubmitRatification] = useMutation<SubmitRatificationData, SubmitRatificationVars>(SUBMIT_RATIFICATION_MUTATION);

  // Current actor identity from a dedicated query — replaces the Phase 3
  // heuristic that guessed identity from whichever claim was most recent.
  // This is the authoritative source for "is this claim mine?" checks.
  const [{ data: actorData }] = useQuery<CurrentActorData>({
    query: CURRENT_ACTOR_QUERY,
  });
  const currentActorEmail = actorData?.currentActor?.email ?? null;

  // Ceremony info — needed to identify the ceremony author for
  // ContributorBanner (shows "authored by {name}" for non-authors).
  const [{ data: ceremonyInfoData }] = useQuery<CeremonyInfoData>({
    query: CEREMONY_INFO_QUERY,
    variables: { featureName },
  });
  const ceremonyAuthor = ceremonyInfoData?.ceremonyInfo?.author ?? null;
  const ceremonyAuthorEmail = ceremonyInfoData?.ceremonyInfo?.authorEmail ?? null;
  const ceremonyStatus = ceremonyInfoData?.ceremonyInfo?.currentRevision?.status ?? null;
  const isContributor = !!(currentActorEmail && ceremonyAuthorEmail && currentActorEmail !== ceremonyAuthorEmail);

  const [claimBusy, setClaimBusy] = useState<string | null>(null);
  const [pendingSelection, setPendingSelection] = useState<EditorSelection | null>(null);
  const progress: SpecProgressInfo[] = progressData?.ceremonyProgress ?? [];
  const progressBySpecType = useMemo(() => {
    const map = new Map<string, SpecProgressInfo>();
    for (const p of progress) map.set(p.specType, p);
    return map;
  }, [progress]);
  // Back-compat alias so the existing code paths that used claimBySpecType
  // continue to work.
  const claimBySpecType = useMemo(() => {
    const map = new Map<string, SpecClaimInfo>();
    for (const p of progress) {
      if (p.claim) map.set(p.specType, p.claim);
    }
    return map;
  }, [progress]);

  const STALE_WINDOW_MS = 3600 * 1000;

  const claimStateFor = useCallback(
    (specType: string): ClaimState => {
      const prog = progressBySpecType.get(specType);
      if (!prog) return { kind: "unclaimed" };

      // Committed variant: a commit record exists on disk. This takes
      // priority over claim state because `commitSpec` retires the
      // claim (`released_at = committed_at`), so the live claim no
      // longer reflects ownership — the commit record is the source
      // of truth for "who owns this".
      if (prog.hasCommit && prog.committer) {
        return {
          kind: "committed",
          claimant: prog.committer,
          ratified: prog.ratified,
        };
      }

      const claim = prog.claim;
      if (!claim) return { kind: "unclaimed" };

      // A claim with released_at set but no commit record is a
      // voluntarily-released claim; treat it as unclaimed.
      if (claim.releasedAt !== null) {
        return { kind: "unclaimed" };
      }

      const lastActivityMs = Date.parse(claim.lastActivityAt);
      const age = Date.now() - lastActivityMs;
      if (age > STALE_WINDOW_MS) {
        const hours = Math.floor(age / (3600 * 1000));
        const staleFor = hours >= 24 ? `${Math.floor(hours / 24)}d` : `${hours}h`;
        return { kind: "stale", claimant: claim.claimant, staleFor };
      }

      if (currentActorEmail && claim.claimantEmail === currentActorEmail) {
        return { kind: "mine", claimant: claim.claimant };
      }

      return {
        kind: "claimed-by-other",
        claimant: claim.claimant,
        committed: false,
      };
    },
    [progressBySpecType, currentActorEmail]
  );

  const handleClaim = useCallback(
    async (specType: string) => {
      setClaimBusy(specType);
      try {
        await executeClaimSpec({ featureName, specType });
        reexecuteProgress({ requestPolicy: "network-only" });
      } finally {
        setClaimBusy(null);
      }
    },
    [featureName, executeClaimSpec, reexecuteProgress]
  );

  const handleRelease = useCallback(
    async (specType: string) => {
      setClaimBusy(specType);
      try {
        await executeReleaseSpec({ featureName, specType });
        reexecuteProgress({ requestPolicy: "network-only" });
      } finally {
        setClaimBusy(null);
      }
    },
    [featureName, executeReleaseSpec, reexecuteProgress]
  );

  const suggestions = suggestionsData?.suggestions ?? [];
  const unresolvedCount = suggestions.filter((s) => s.status === "unresolved").length;

  // Claim state for the active tab. Drives ReadOnlyBanner + SpecEditor
  // read-only mode + CommitBar mode switching.
  const activeTabClaimState = useMemo<ClaimState>(
    () => claimStateFor(activeTab),
    [claimStateFor, activeTab]
  );
  const isClaimant = activeTabClaimState.kind === "mine";

  // Ratification context for the active tab. Built whenever the active
  // tab is committed so CommitBar can render RatifyControl for
  // non-committer viewers.
  const [ratifyBusy, setRatifyBusy] = useState(false);
  const activeProgress = progressBySpecType.get(activeTab);

  const handleRatify = useCallback(
    async (verdict: "approve" | "reject", comment?: string) => {
      setRatifyBusy(true);
      try {
        const result = await executeSubmitRatification({
          featureName,
          specType: activeTab,
          verdict,
          comment,
        });
        if (!result.error) {
          reexecuteProgress({ requestPolicy: "network-only" });
        }
      } finally {
        setRatifyBusy(false);
      }
    },
    [featureName, activeTab, executeSubmitRatification, reexecuteProgress]
  );

  const ratifyContext = useMemo(() => {
    if (!activeProgress || !activeProgress.hasCommit) return undefined;
    return {
      approvalCount: activeProgress.approvalCount,
      approvalThreshold: activeProgress.ratificationThreshold,
      hasVoted: activeProgress.hasVoted,
      viewerIsCommitter:
        !!currentActorEmail &&
        activeProgress.committerEmail === currentActorEmail,
      viewerVerdict: null as "approve" | "reject" | null,
      busy: ratifyBusy,
      onApprove: (comment?: string) => handleRatify("approve", comment),
      onReject: (comment: string) => handleRatify("reject", comment),
    };
  }, [activeProgress, currentActorEmail, ratifyBusy, handleRatify]);

  // Progress overview rows. Composed from drafts + progress query + suggestions.
  // Real status pills now — drafting/committed/ratified/rejected — derived
  // from the per-spec progress query.
  const progressRows = useMemo<ProgressRowData[]>(() => {
    const draftedSpecs = Object.keys(drafts);
    if (draftedSpecs.length === 0) return [];

    return draftedSpecs.map((specType): ProgressRowData => {
      const prog = progressBySpecType.get(specType);
      const claim = prog?.claim;
      const openSuggestions = suggestions.filter(
        (s) => s.status === "unresolved" && s.specType === specType
      ).length;

      // Claimant: prefer the committer for committed specs, fall back
      // to the active claim otherwise. This matches how claimStateFor
      // decides what to display.
      let claimantName: string | null = null;
      let claimantStatus: ProgressRowData["claimantStatus"] = "unclaimed";
      if (prog?.hasCommit && prog.committer) {
        claimantName = prog.committer;
        claimantStatus = "released";
      } else if (claim) {
        claimantName = claim.claimant;
        if (claim.releasedAt !== null) {
          claimantStatus = "released";
        } else {
          const age = Date.now() - Date.parse(claim.lastActivityAt);
          claimantStatus = age > STALE_WINDOW_MS ? "stale" : "active";
        }
      }

      // Status pill — real status derived from progress query.
      let status: ProgressRowData["status"] = "drafting";
      if (prog) {
        if (prog.ratified) {
          status = "ratified";
        } else if (prog.hasRejection) {
          status = "rejected";
        } else if (prog.hasCommit) {
          status = "committed";
        }
      }

      return {
        specType,
        claimant: claimantName,
        claimantStatus,
        validation: specType === activeTab && vsData?.validationState ? (
          vsData.validationState.failCount > 0
            ? "fail"
            : vsData.validationState.warnCount > 0
              ? "warn"
              : "pass"
        ) : "pending",
        validationWarnings:
          specType === activeTab && vsData?.validationState
            ? vsData.validationState.warnCount
            : 0,
        suggestionsOpen: openSuggestions,
        status,
      };
    });
  }, [drafts, progressBySpecType, suggestions, activeTab, vsData]);

  // Must be declared before the subscription callback that references it
  const draftsLoaded = useRef(false);

  // Subscribe to draft generation progress
  useSubscription<DraftGenerationProgressData>(
    { query: DRAFT_GENERATION_PROGRESS_SUBSCRIPTION, variables: { feature: featureName }, pause: !generating },
    (_prev, data) => {
      const event = data?.draftGenerationProgress;
      if (!event) return data;
      if (event.status === "complete") {
        // Generation finished -- refetch drafts and validation
        setGenerating(false);
        if (genTimerRef.current) { clearInterval(genTimerRef.current); genTimerRef.current = null; }
        reexecuteDrafts({ requestPolicy: "network-only" });
        reexecuteVs({ requestPolicy: "network-only" });
        // Force reload of content from persisted drafts
        draftsLoaded.current = false;
      } else if (event.status === "error") {
        setGenerating(false);
        setGenError(event.error || "Generation failed");
        if (genTimerRef.current) { clearInterval(genTimerRef.current); genTimerRef.current = null; }
      }
      return data;
    },
  );

  // Query for persisted decomposition result (loaded on complete or page load)
  const [{ data: decompData }, reexecuteDecomposition] = useQuery<DecompositionResultData>({
    query: DECOMPOSITION_RESULT_QUERY,
    variables: { featureName },
  });

  // Subscribe to decomposition progress
  useSubscription<DecompositionProgressData>(
    { query: DECOMPOSITION_PROGRESS_SUBSCRIPTION, variables: { feature: featureName }, pause: !decomposing },
    (_prev, data) => {
      const event = data?.decompositionProgress;
      if (!event) return data;
      setDecomposeStage(event.stage);
      if (event.stage === "complete") {
        // Don't set decomposing=false yet — wait for the query result
        // to load so the panel doesn't flash away
        if (decomposeTimerRef.current) { clearInterval(decomposeTimerRef.current); decomposeTimerRef.current = null; }
        reexecuteDecomposition({ requestPolicy: "network-only" });
      } else if (event.stage === "error") {
        setDecomposing(false);
        setDecomposeError(event.error || "Decomposition failed");
        if (decomposeTimerRef.current) { clearInterval(decomposeTimerRef.current); decomposeTimerRef.current = null; }
      }
      return data;
    },
  );

  // When persisted result loads, update state (don't auto-show task board)
  useEffect(() => {
    if (decompData?.decompositionResult) {
      setDecompositionResult(decompData.decompositionResult);
      if (decomposing) {
        setDecomposing(false);
      }
    }
  }, [decompData, decomposing]);

  const models = modelsData?.ceremonyModels ?? [];
  const [selectedModel, setSelectedModel] = useState("");

  useEffect(() => {
    if (models.length > 0 && !selectedModel) setSelectedModel(models[0].id);
  }, [models, selectedModel]);

  // Load persisted drafts
  useEffect(() => {
    if (!draftsData?.allSpecDrafts) return;
    const map: Record<string, SpecDraft> = {};
    const contentMap: Record<string, string> = {};
    for (const d of draftsData.allSpecDrafts) {
      map[d.specType] = d;
      contentMap[d.specType] = d.content;
    }
    setDrafts(map);
    if (!draftsLoaded.current && Object.keys(map).length > 0) {
      draftsLoaded.current = true;
      setEditContent(contentMap);
    }
  }, [draftsData]);

  const validationState = vsData?.validationState ?? null;
  const activeDraft = drafts[activeTab];
  const activeContent = editContent[activeTab] ?? "";
  const hasDraft = !!activeDraft;

  // Build tab list: core tabs + any child RFC tabs from loaded drafts
  const tabs = useMemo(() => {
    const coreTypes = new Set(CORE_TABS.map((t) => t.type));
    const childTabs = Object.keys(drafts)
      .filter((t) => !coreTypes.has(t))
      .sort()
      .map((t) => ({ type: t, label: tabLabel(t) }));
    return [...CORE_TABS, ...childTabs];
  }, [drafts]);

  // Can generate this tab? PRD always, Design needs PRD, RFC needs Design
  // Child RFCs require the parent RFC
  const prereq = REQUIRES[activeTab] ?? (activeTab.startsWith("rfc-") ? "rfc" : null);
  const canGenerate = !prereq || !!drafts[prereq];

  // Stale tracking
  const tier2CheckedAt = useMemo(() => {
    if (!validationState) return 0;
    const t2 = validationState.dimensions.filter((d) => d.tier === 2);
    if (!t2.length) return 0;
    return Math.max(...t2.map((d) => d.checkedAt ? new Date(d.checkedAt).getTime() : 0));
  }, [validationState]);
  const draftEditedSinceLastCheck = lastEditTime > tier2CheckedAt && tier2CheckedAt > 0;

  // Word count
  const wordCount = useMemo(() => {
    if (!activeContent) return 0;
    return activeContent.split(/\s+/).filter(Boolean).length;
  }, [activeContent]);

  // ── Handlers ─────────────────────────────────────────────────

  const handleGenerate = useCallback(async () => {
    if (!selectedModel || !canGenerate) return;
    setGenerating(true);
    setGenError(null);
    setGenElapsed(0);
    const start = Date.now();
    genTimerRef.current = setInterval(() => setGenElapsed(Math.floor((Date.now() - start) / 1000)), 1000);

    try {
      const result = await executeGenerate({
        featureName,
        specType: activeTab,
        model: selectedModel,
        refinement: refinement || undefined,
      });
      if (result.error) {
        setGenError(result.error.message);
        setGenerating(false);
        if (genTimerRef.current) { clearInterval(genTimerRef.current); genTimerRef.current = null; }
      } else if (result.data?.generateDraft.status === "error") {
        setGenError(result.data.generateDraft.error || "Generation failed");
        setGenerating(false);
        if (genTimerRef.current) { clearInterval(genTimerRef.current); genTimerRef.current = null; }
      }
      // If status is "generating", the subscription will handle completion
      if (result.data?.generateDraft.status === "generating") {
        setRefinement("");
      }
    } catch (err: any) {
      setGenError(err?.message || "Generation failed");
      setGenerating(false);
      if (genTimerRef.current) { clearInterval(genTimerRef.current); genTimerRef.current = null; }
    }
  }, [featureName, activeTab, selectedModel, refinement, canGenerate, executeGenerate]);

  const handleContentChange = useCallback((content: string) => {
    setEditContent((prev) => ({ ...prev, [activeTab]: content }));
    setLastEditTime(Date.now());
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(async () => {
      setSaving(true);
      try {
        await executeUpdate({ featureName, specType: activeTab, content });
        reexecuteVs({ requestPolicy: "network-only" });
      } finally {
        setSaving(false);
      }
    }, 500);
  }, [featureName, activeTab, executeUpdate, reexecuteVs]);

  const handleValidate = useCallback(async () => {
    setValidating(true);
    try {
      await executeValidate({ featureName, specType: activeTab, model: selectedModel || undefined });
      reexecuteVs({ requestPolicy: "network-only" });
    } finally {
      setValidating(false);
    }
  }, [featureName, activeTab, selectedModel, executeValidate, reexecuteVs]);

  const handleIssueClick = useCallback((issue: ValidationIssue) => {
    setGutterExpanded(true);
    if (issue.section || issue.line) {
      setTimeout(() => {
        editorRef.current?.scrollToSection(issue.section || "", issue.line);
      }, 50);
    }
  }, []);

  const handleAcceptSuggestion = useCallback(async (id: string) => {
    await executeResolveSuggestion({ featureName, suggestionId: id, action: "accept" });
    reexecuteSuggestions({ requestPolicy: "network-only" });
  }, [featureName, executeResolveSuggestion, reexecuteSuggestions]);

  const handleDismissSuggestion = useCallback(async (id: string, reason: string) => {
    await executeResolveSuggestion({ featureName, suggestionId: id, action: "dismiss", reason });
    reexecuteSuggestions({ requestPolicy: "network-only" });
  }, [featureName, executeResolveSuggestion, reexecuteSuggestions]);

  const handleReplySuggestion = useCallback(async (id: string, text: string) => {
    await executeReplySuggestion({ featureName, suggestionId: id, text });
    reexecuteSuggestions({ requestPolicy: "network-only" });
  }, [featureName, executeReplySuggestion, reexecuteSuggestions]);

  const handleCreateSuggestion = useCallback(async (sectionId: string, sectionTitle: string, text: string) => {
    await executeCreateSuggestion({ featureName, specType: activeTab, sectionId, sectionTitle, text });
    reexecuteSuggestions({ requestPolicy: "network-only" });
  }, [featureName, activeTab, executeCreateSuggestion, reexecuteSuggestions]);

  const handleDecompose = useCallback(async () => {
    setDecomposing(true);
    setDecomposeElapsed(0);
    setDecomposeStage("loading_specs");
    setDecomposeError(null);
    setDecompositionResult(null);
    decomposeTimerRef.current = setInterval(() => {
      setDecomposeElapsed((prev) => prev + 1);
    }, 1000);

    const result = await executeDecompose({
      featureName,
      specType: activeTab,
      model: selectedModel || undefined,
    });

    // If the mutation itself returned an error (input validation), stop
    if (result.data?.decomposeDraft?.status === "error") {
      setDecomposing(false);
      setDecomposeError(result.data.decomposeDraft.error || "Decomposition failed");
      if (decomposeTimerRef.current) { clearInterval(decomposeTimerRef.current); decomposeTimerRef.current = null; }
    } else if (result.error) {
      setDecomposing(false);
      setDecomposeError(result.error.message);
      if (decomposeTimerRef.current) { clearInterval(decomposeTimerRef.current); decomposeTimerRef.current = null; }
    }
    // If status is "running", the subscription handles the rest
  }, [featureName, activeTab, selectedModel, executeDecompose]);

  const handleCancelDecompose = useCallback(() => {
    setDecomposing(false);
    setDecomposeStage("loading_specs");
    setDecomposeError(null);
    if (decomposeTimerRef.current) { clearInterval(decomposeTimerRef.current); decomposeTimerRef.current = null; }
  }, []);

  // Child RFC generation from decomposition result
  const [generatingChildRfcs, setGeneratingChildRfcs] = useState(false);

  const handleGenerateChildRfcs = useCallback(async () => {
    if (!decompositionResult || !selectedModel) return;
    setGeneratingChildRfcs(true);
    try {
      // Build children from decomposition tasks, grouped by spec references
      const children = decompositionResult.tasks.map((task) => ({
        name: task.id,
        userStoryIds: task.specReferences?.map((r) => r.requirement).filter(Boolean) ?? [],
        dependsOn: task.dependsOn.length > 0 ? task.dependsOn : undefined,
      }));

      const result = await executeGenerateChildRfcs({
        featureName,
        decomposition: { children },
        model: selectedModel,
      });

      if (result.error) {
        setDecomposeError(result.error.message);
      } else if (result.data?.generateChildRfcs.status === "error") {
        setDecomposeError(result.data.generateChildRfcs.error || "Generation failed");
      } else {
        // Refresh drafts so new child RFC tabs appear
        reexecuteDrafts({ requestPolicy: "network-only" });
      }
    } catch (err: any) {
      setDecomposeError(err?.message || "Child RFC generation failed");
    } finally {
      setGeneratingChildRfcs(false);
    }
  }, [decompositionResult, selectedModel, featureName, executeGenerateChildRfcs, reexecuteDrafts]);

  // Extract section headings from active spec content for the suggestion composer
  const specSections = useMemo(() => {
    if (!activeContent) return [];
    const headings: string[] = [];
    for (const line of activeContent.split("\n")) {
      const match = line.match(/^#{1,6}\s+(.+)$/);
      if (match) headings.push(match[1].trim());
    }
    return headings;
  }, [activeContent]);

  const handleCommit = useCallback(async () => {
    setCommitting(true);
    setCommitError(null);
    try {
      const result = await executeCommitSpec({ featureName, specType: activeTab });
      if (result.error) {
        setCommitError(result.error.message);
      } else {
        setCommitDialogOpen(false);
        reexecuteProgress({ requestPolicy: "network-only" });
      }
    } finally {
      setCommitting(false);
    }
  }, [featureName, activeTab, executeCommitSpec, reexecuteProgress]);

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || !e.shiftKey) return;
      if (e.key === "r") { e.preventDefault(); handleValidate(); }
      else if (e.key === "s") { e.preventDefault(); setSidebarOpen((v) => !v); }
      else if (e.key === "p") { e.preventDefault(); setMode("preview"); }
      else if (e.key === "e") { e.preventDefault(); setMode("edit"); }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [handleValidate]);

  // Cleanup
  useEffect(() => () => {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    if (genTimerRef.current) clearInterval(genTimerRef.current);
    if (decomposeTimerRef.current) clearInterval(decomposeTimerRef.current);
  }, []);

  // ── Render ───────────────────────────────────────────────────

  // Task board: full takeover when active
  if (showTaskBoard && decompositionResult) {
    return (
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {/* Minimal nav bar to get back */}
        <div style={{
          display: "flex", alignItems: "center", gap: 12,
          padding: "6px 16px",
          borderBottom: "1px solid var(--color-border-light)",
          background: "var(--color-bg-card)",
          flexShrink: 0,
        }}>
          <button
            onClick={() => setShowTaskBoard(false)}
            style={{
              display: "flex", alignItems: "center", gap: 4,
              padding: "4px 10px", fontSize: 11, fontWeight: 500,
              color: "var(--color-text-secondary)", background: "var(--color-bg-elevated)",
              border: "1px solid var(--color-border)", borderRadius: 4, cursor: "pointer",
            }}
          >
            ← Editor
          </button>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--color-text-tertiary)" }}>
            {featureName}
          </span>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--color-accent)" }}>
            RFC
          </span>
        </div>
        <div style={{ flex: 1, overflow: "hidden" }}>
          <TaskBoard
            tasks={decompositionResult.tasks}
            featureName={featureName}
            intent={contextPackage.intent}
            gate={decompositionResult.gate}
            onVerify={() => {
              reexecuteDecomposition({ requestPolicy: "network-only" });
            }}
            onApprove={() => {
              // TODO: write task files + lock plan
              setShowTaskBoard(false);
            }}
          />
        </div>
      </div>
    );
  }

  return (
    <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
      {/* Context panel */}
      <ContextPanel
        featureName={featureName}
        contextPackage={contextPackage}
        onRefine={onRefine}
        refining={refining}
        progressRows={progressRows}
        activeSpecType={activeTab}
        onProgressRowClick={(specType) => setActiveTab(specType)}
      />

      {/* Editor area */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", background: "var(--color-bg-card)", borderRadius: "10px 0 0 0" }}>
        {/* Tab bar */}
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "0 16px", borderBottom: "1px solid var(--color-border-light)", flexShrink: 0,
        }}>
          <div style={{ display: "flex", gap: 0, alignItems: "center" }}>
            {tabs.map(({ type, label }) => {
              const exists = !!drafts[type];
              const active = activeTab === type;
              const req = REQUIRES[type];
              const locked = req && !drafts[req];
              const tabClaimState = claimStateFor(type);
              return (
                <div
                  key={type}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                    padding: "10px 16px",
                    borderBottom: active ? "2px solid var(--color-accent)" : "2px solid transparent",
                    opacity: locked ? 0.4 : 1,
                    transition: "all 150ms ease",
                  }}
                >
                  <button
                    onClick={() => !locked && setActiveTab(type)}
                    disabled={!!locked}
                    style={{
                      fontSize: 12,
                      fontWeight: active ? 600 : 400,
                      color: locked
                        ? "var(--color-text-tertiary)"
                        : active
                          ? "var(--color-text)"
                          : "var(--color-text-secondary)",
                      background: "transparent",
                      border: "none",
                      padding: 0,
                      cursor: locked ? "not-allowed" : "pointer",
                    }}
                  >
                    {label}
                    {exists && (
                      <span style={{
                        display: "inline-block", width: 6, height: 6, borderRadius: 3,
                        background: "var(--color-emerald)", marginLeft: 6, verticalAlign: "middle",
                      }} />
                    )}
                  </button>
                  <TabClaimBadge
                    state={tabClaimState}
                    onClaim={() => handleClaim(type)}
                    onRelease={() => handleRelease(type)}
                    busy={claimBusy === type}
                  />
                </div>
              );
            })}
          </div>

          {/* Right side: mode toggle + validate */}
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            {saving && <span style={{ color: "var(--color-text-tertiary)", fontSize: 11 }}>Saving...</span>}
            {hasDraft && (
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--color-text-tertiary)" }}>
                {wordCount.toLocaleString()} words
              </span>
            )}
            {hasDraft && (
              <div style={{ display: "flex", gap: 2, background: "var(--color-bg-elevated)", borderRadius: 4, padding: 2 }}>
                <button
                  onClick={() => setMode("preview")}
                  title="Preview (⌘⇧P)"
                  style={{
                    display: "flex", alignItems: "center", padding: "3px 6px",
                    background: mode === "preview" ? "var(--color-bg-card)" : "transparent",
                    border: "none", borderRadius: 3, cursor: "pointer",
                    color: mode === "preview" ? "var(--color-text)" : "var(--color-text-tertiary)",
                  }}
                >
                  <Eye size={13} strokeWidth={1.5} />
                </button>
                <button
                  onClick={() => setMode("edit")}
                  title="Edit (⌘⇧E)"
                  style={{
                    display: "flex", alignItems: "center", padding: "3px 6px",
                    background: mode === "edit" ? "var(--color-bg-card)" : "transparent",
                    border: "none", borderRadius: 3, cursor: "pointer",
                    color: mode === "edit" ? "var(--color-text)" : "var(--color-text-tertiary)",
                  }}
                >
                  <Pencil size={13} strokeWidth={1.5} />
                </button>
              </div>
            )}
            {hasDraft && (
              <button
                onClick={() => setSidebarOpen((v) => !v)}
                title="Toggle suggestions (⌘⇧S)"
                style={{
                  position: "relative",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  width: 30, height: 30, borderRadius: 6,
                  background: sidebarOpen ? "var(--color-accent-dim)" : "transparent",
                  border: "none", cursor: "pointer",
                  color: sidebarOpen ? "var(--color-accent)" : "var(--color-text-tertiary)",
                  transition: "all 150ms",
                }}
              >
                <MessageCircle size={15} />
                {unresolvedCount > 0 && (
                  <span style={{
                    position: "absolute", top: 2, right: 2,
                    minWidth: 14, height: 14,
                    background: "var(--color-amber)",
                    color: "var(--color-bg)", fontFamily: "var(--font-mono)",
                    fontSize: 9, fontWeight: 600,
                    borderRadius: 7, display: "flex", alignItems: "center", justifyContent: "center",
                    padding: "0 3px",
                  }}>
                    {unresolvedCount}
                  </span>
                )}
              </button>
            )}
            {hasDraft && (
              <button
                onClick={handleValidate}
                disabled={validating}
                style={{
                  padding: "4px 10px", fontSize: 11, fontWeight: 500,
                  color: validating ? "var(--color-text-tertiary)" : "var(--color-text-secondary)",
                  background: "var(--color-bg-elevated)", border: "1px solid var(--color-border)",
                  borderRadius: 4, cursor: validating ? "default" : "pointer",
                }}
                title="Run full validation (⌘⇧R)"
              >
                {validating ? "Checking..." : "Validate"}
              </button>
            )}
            {hasDraft && activeTab.startsWith("rfc") && (
              <div style={{ display: "flex", alignItems: "center", gap: 0, borderRadius: 4, overflow: "hidden", border: "1px solid var(--color-accent-glow)" }}>
                <button
                  onClick={() => {
                    if (decomposing) return;
                    // Toggle the decomposition panel (slide-out)
                    if (decompositionResult) {
                      setDecompositionResult(null);
                    } else if (decompData?.decompositionResult) {
                      setDecompositionResult(decompData.decompositionResult);
                    } else {
                      handleDecompose();
                    }
                  }}
                  disabled={decomposing || !selectedModel}
                  style={{
                    padding: "4px 10px", fontSize: 11, fontWeight: 500,
                    color: decomposing ? "var(--color-text-tertiary)" : "var(--color-accent)",
                    background: "var(--color-accent-dim)", border: "none",
                    cursor: decomposing || !selectedModel ? "default" : "pointer",
                    transition: "all 150ms",
                  }}
                  title={selectedModel ? `Decompose with ${selectedModel}` : "Select a model first"}
                >
                  {decomposing
                    ? `Decomposing${decomposeElapsed > 0 ? ` (${decomposeElapsed}s)` : "..."}`
                    : decompositionResult
                      ? "Tasks"
                      : decompData?.decompositionResult
                        ? "Tasks"
                        : "Decompose"}
                </button>
                <select
                  value={selectedModel}
                  onChange={(e) => setSelectedModel(e.target.value)}
                  style={{
                    padding: "4px 4px 4px 2px", fontSize: 10,
                    fontFamily: "var(--font-mono)",
                    color: "var(--color-accent)", background: "var(--color-accent-dim)",
                    border: "none", borderLeft: "1px solid var(--color-accent-glow)",
                    cursor: "pointer", outline: "none",
                    maxWidth: 110,
                  }}
                  title="Select model for decomposition"
                >
                  {models.map((m) => (
                    <option key={m.id} value={m.id}>{m.label || m.id}</option>
                  ))}
                </select>
              </div>
            )}
          </div>
        </div>

        {/* Content area */}
        {hasDraft ? (
          <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", minHeight: 0 }}>
            {/* Contributor banner for non-authors viewing the spec */}
            {isContributor &&
              activeTabClaimState.kind !== "claimed-by-other" &&
              activeTabClaimState.kind !== "stale" &&
              ceremonyAuthor &&
              ceremonyStatus && (
              <ContributorBanner
                authorName={ceremonyAuthor}
                status={ceremonyStatus}
              />
            )}
            {/* Read-only banner for non-claimants of the active tab */}
            {(activeTabClaimState.kind === "claimed-by-other" ||
              activeTabClaimState.kind === "stale") && (
              <div style={{ padding: "12px 20px 0 20px" }}>
                <ReadOnlyBanner
                  kind={activeTabClaimState.kind === "stale" ? "stale" : "standard"}
                  claimant={activeTabClaimState.claimant}
                  staleFor={
                    activeTabClaimState.kind === "stale"
                      ? activeTabClaimState.staleFor
                      : undefined
                  }
                  onTakeover={
                    activeTabClaimState.kind === "stale"
                      ? () => handleClaim(activeTab)
                      : undefined
                  }
                />
              </div>
            )}
            <div style={{ flex: 1, overflow: "hidden", position: "relative" }}>
              {mode === "edit" ? (
                <SpecEditor
                  ref={editorRef}
                  key={activeTab}
                  content={activeContent}
                  specType={activeTab}
                  onChange={handleContentChange}
                  readOnly={!isClaimant}
                  onSelectionChange={
                    !isClaimant
                      ? (sel) => setPendingSelection(sel)
                      : undefined
                  }
                />
              ) : (
                <SpecPreview content={activeContent} />
              )}
              {/* Non-claimant popover: anchored to a text selection in
                  the read-only editor, offers a single "Leave suggestion"
                  action that creates a spec_type-tagged suggestion. */}
              {!isClaimant && pendingSelection && (
                <SuggestionPopover
                  anchorRect={pendingSelection.rect}
                  onLeaveSuggestion={() => {
                    const sel = pendingSelection;
                    setPendingSelection(null);
                    setSidebarOpen(true);
                    // Fire createSuggestion with the inferred section,
                    // reusing the same handler the sidebar uses.
                    handleCreateSuggestion(
                      sel.sectionId ?? "inline",
                      sel.sectionTitle ?? "Selection",
                      `> ${sel.text.trim()}\n\n`,
                    );
                  }}
                  onDismiss={() => setPendingSelection(null)}
                />
              )}
            </div>
            {activeTab.startsWith("rfc") && (decomposing || decompositionResult || decomposeError) && (
              <DecompositionPanel
                result={decompositionResult}
                onClose={() => { setDecompositionResult(null); setDecomposeError(null); }}
                progress={decomposing || decomposeError ? {
                  stage: decomposeError ? "error" : decomposeStage,
                  elapsed: decomposeElapsed,
                  error: decomposeError,
                } : null}
                onCancel={handleCancelDecompose}
                onOpenBoard={decompositionResult ? () => setShowTaskBoard(true) : undefined}
                onGenerateChildRfcs={decompositionResult && isClaimant ? handleGenerateChildRfcs : undefined}
                generatingChildRfcs={generatingChildRfcs}
              />
            )}
            {commitError && (
              <div style={{ padding: "6px 20px", fontSize: 11, color: "var(--color-red)", background: "rgba(239, 68, 100, 0.06)", borderTop: "1px solid var(--color-border)" }}>
                {commitError}
              </div>
            )}
            <CommitBar
              activeSpecType={activeTab}
              claimState={activeTabClaimState}
              validationState={validationState}
              unresolvedSuggestionCount={unresolvedCount}
              resolvedSuggestionCount={suggestions.filter((s) => s.status !== "unresolved").length}
              onCommit={() => setCommitDialogOpen(true)}
              ratify={ratifyContext}
            />
          </div>
        ) : (
          /* Generate prompt */
          <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 16, padding: 48 }}>
            {genError && (
              <div style={{ fontSize: 12, color: "var(--color-red)", maxWidth: 400, textAlign: "center", marginBottom: 8 }}>
                {genError}
              </div>
            )}

            {!canGenerate ? (
              <span style={{ fontSize: 13, color: "var(--color-text-tertiary)", textAlign: "center", maxWidth: 320, lineHeight: 1.5 }}>
                Generate the {REQUIRES[activeTab]?.toUpperCase()} first before creating the {activeTab.toUpperCase()}.
              </span>
            ) : (
              <>
                <span style={{ fontSize: 13, color: "var(--color-text-secondary)", textAlign: "center", maxWidth: 360, lineHeight: 1.5 }}>
                  {activeTab === "prd"
                    ? "Generate a PRD from the assembled context."
                    : activeTab === "design"
                      ? "Generate a Design spec grounded in the PRD."
                      : "Generate an RFC grounded in the PRD and Design spec."}
                </span>

                {/* Optional refinement */}
                <textarea
                  value={refinement}
                  onChange={(e) => setRefinement(e.target.value)}
                  placeholder={`Optional: guide the ${activeTab.toUpperCase()} generation (e.g. "focus on the query subsystem, stories S1-S6")`}
                  rows={2}
                  style={{
                    width: "100%", maxWidth: 400, padding: "8px 12px", fontSize: 12,
                    color: "var(--color-text-secondary)", background: "var(--color-bg-elevated)",
                    border: "1px solid var(--color-border)", borderRadius: 6,
                    resize: "vertical", fontFamily: "var(--font-sans)", lineHeight: 1.5,
                  }}
                />

                {/* Model selector */}
                {models.length > 1 && (
                  <select
                    value={selectedModel}
                    onChange={(e) => setSelectedModel(e.target.value)}
                    style={{
                      padding: "6px 10px", fontSize: 12, color: "var(--color-text-secondary)",
                      background: "var(--color-bg-elevated)", border: "1px solid var(--color-border)",
                      borderRadius: 4, cursor: "pointer", minWidth: 180,
                    }}
                  >
                    {models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
                  </select>
                )}

                <button
                  onClick={handleGenerate}
                  disabled={generating || !selectedModel}
                  style={{
                    padding: "10px 24px", fontSize: 13, fontWeight: 600,
                    color: generating ? "var(--color-text-tertiary)" : "var(--color-bg)",
                    background: generating ? "var(--color-bg-elevated)" : "var(--color-accent)",
                    border: "none", borderRadius: 6,
                    cursor: generating ? "default" : "pointer", transition: "all 150ms ease",
                  }}
                >
                  {generating
                    ? `Generating${genElapsed > 0 ? ` (${genElapsed}s)` : "..."}`
                    : `Generate ${activeTab.toUpperCase()}`}
                </button>
              </>
            )}
          </div>
        )}
      </div>

      {/* Commit dialog */}
      <CommitDialog
        isOpen={commitDialogOpen}
        featureName={featureName}
        validationState={validationState}
        suggestionSummary={{
          resolved: suggestions.filter((s) => s.status !== "unresolved").length,
          pending: unresolvedCount,
        }}
        onCommit={handleCommit}
        onCancel={() => { setCommitDialogOpen(false); setCommitError(null); }}
        committing={committing}
      />

      {/* Suggestion sidebar — filtered to the active tab's spec_type
          so claimants see only suggestions on their spec and non-claimants
          see only suggestions they might want to leave on the spec they
          are currently viewing. */}
      {hasDraft && sidebarOpen && (
        <SuggestionSidebar
          suggestions={suggestions.filter(
            (s) => s.specType === activeTab || !s.specType
          )}
          isAuthor={isClaimant}
          onAccept={handleAcceptSuggestion}
          onDismiss={handleDismissSuggestion}
          onReply={handleReplySuggestion}
          onCreateSuggestion={!isClaimant ? handleCreateSuggestion : undefined}
          specSections={specSections}
        />
      )}

      {/* Validation gutter */}
      {hasDraft && (
        <ValidationGutter
          validationState={validationState}
          expanded={gutterExpanded}
          onToggle={() => setGutterExpanded((v) => !v)}
          onIssueClick={handleIssueClick}
          draftEditedSinceLastCheck={draftEditedSinceLastCheck}
          loading={validating}
        />
      )}
    </div>
  );
}
