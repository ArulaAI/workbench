"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQuery, useSubscription } from "urql";
import { ErrorBoundary } from "@/components/shared/error-boundary";
import { IconRail } from "@/components/landing/IconRail";
import { Header } from "@/components/layout/header";
import {
  AnswerReviewCarousel,
  AuthoringBar,
  BlockingNotice,
  ConflictBanner,
  CoverageEditCard,
  DraftPreview,
  HelperUnavailable,
  QuestionBatch,
  QuestionCard,
  SelfReviewSummary,
  type SaveState,
} from "@/components/ceremony/guided";
import {
  ADD_AUTHORING_REVIEW_COMMENT_MUTATION,
  AUTHORING_SESSION_CHANGED_SUBSCRIPTION,
  AUTHORING_SESSION_QUERY,
  PREPARE_AUTHORING_COMMIT_MUTATION,
  PUBLISH_AUTHORING_DRAFT_MUTATION,
  REPLAN_AUTHORING_MUTATION,
  REVISE_AUTHORING_COVERAGE_MUTATION,
  REVISE_AUTHORING_SECTION_MUTATION,
  REVISE_AUTHORING_DOCUMENT_MUTATION,
  SUBMIT_AUTHORING_REVIEW_COMMENTS_MUTATION,
  SELECT_AUTHORING_ACTION_MUTATION,
  SUBMIT_AUTHORING_ANSWER_MUTATION,
  type AuthoringAction,
  type AuthoringSession,
  type AuthoringReviewComment,
  type AuthoringSessionChangedData,
  type AuthoringSessionData,
  type PrepareAuthoringCommitData,
  type PublishAuthoringDraftData,
  type ReplanAuthoringData,
} from "@/lib/graphql/queries/authoring";

/**
 * Route: /define/:feature/authoring/:artifact
 *
 * Three regions: readiness, question batch or repair question, generated draft. Every question,
 * option, and message is rendered from the helper payload; this page owns
 * layout, revision discipline, and nothing else.
 */
export default function AuthoringPage() {
  const params = useParams<{ feature: string; artifact: string }>();
  const router = useRouter();
  const featureName = params.feature;
  const artifactType = params.artifact ?? "prd";
  const artifactLabel = artifactType === "design" ? "Design" : artifactType === "rfc" ? "Technical RFC" : "PRD";

  const [session, setSession] = useState<AuthoringSession | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("saved");
  const [conflictAt, setConflictAt] = useState<number | null>(null);
  const [conflictCurrentRevision, setConflictCurrentRevision] = useState<number | null>(null);
  const [draftText, setDraftText] = useState("");
  const [highlightQuestionId, setHighlightQuestionId] = useState<string | null>(null);
  const [editingCoverageId, setEditingCoverageId] = useState<string | null>(null);
  const [editingCoverageAnswer, setEditingCoverageAnswer] = useState("");
  const [mutationError, setMutationError] = useState<string | null>(null);
  const [preparingCommit, setPreparingCommit] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [globalFeedback, setGlobalFeedback] = useState("");
  const [replanning, setReplanning] = useState(false);
  const [planningRetry, setPlanningRetry] = useState(0);
  const [draftDirty, setDraftDirty] = useState(false);
  const [answerDirty, setAnswerDirty] = useState(false);
  const [draftResetKey, setDraftResetKey] = useState(0);
  const [answerResetKey, setAnswerResetKey] = useState(0);
  const submittingRef = useRef(false);
  const sessionRef = useRef<AuthoringSession | null>(null);
  const draftDirtyRef = useRef(false);
  const answerDirtyRef = useRef(false);
  const replanAttemptRef = useRef<Set<string>>(new Set());
  const questionColumnRef = useRef<HTMLDivElement>(null);
  const mountedRef = useRef(false);
  const routeIdentityRef = useRef(`${featureName}:${artifactType}`);
  routeIdentityRef.current = `${featureName}:${artifactType}`;
  sessionRef.current = session;
  draftDirtyRef.current = draftDirty;
  answerDirtyRef.current = answerDirty;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // urql subscribes to the operation while rendering, and its guard against
  // dispatching into other components during that window reads a React
  // internal that React 19 renamed. An outgoing route holding the same
  // operation key would therefore be updated mid-render. Subscribing after
  // mount puts that route's teardown first.
  const [subscribed, setSubscribed] = useState(false);
  useEffect(() => setSubscribed(true), []);

  const [{ data, fetching, error }, refetch] = useQuery<AuthoringSessionData>({
    query: AUTHORING_SESSION_QUERY,
    variables: { featureName, artifactType },
    pause: !subscribed,
    requestPolicy: "network-only",
  });

  useEffect(() => {
    const incoming = data?.authoringSession;
    if (!incoming) return;
    setSession((current) => {
      if (!current) return incoming;

      const currentRevision = current.revision;
      const incomingRevision = incoming.revision;
      // A mutation can complete before urql replaces the query result that
      // started it. Never replay that older response over the mutation result:
      // doing so made this tab submit revision 0 after planning had saved 1.
      if (
        currentRevision !== null &&
        incomingRevision !== null &&
        incomingRevision < currentRevision
      ) {
        return current;
      }
      if (
        (draftDirtyRef.current || answerDirtyRef.current) &&
        currentRevision !== null &&
        incomingRevision !== currentRevision
      ) {
        setSaveState("conflict");
        setConflictAt(currentRevision);
        setConflictCurrentRevision(incomingRevision);
        return current;
      }
      return incoming;
    });
  }, [data]);

  // A checkpoint written by the CLI or another tab refreshes the view, but
  // never while this tab has a mutation in flight.
  useSubscription<AuthoringSessionChangedData>(
    {
      query: AUTHORING_SESSION_CHANGED_SUBSCRIPTION,
      variables: { feature: featureName },
      pause: !subscribed,
    },
    (_prev, event) => {
      const incoming = event?.authoringSessionChanged;
      const current = sessionRef.current;
      if (
        incoming &&
        incoming.artifactType === artifactType &&
        !submittingRef.current &&
        incoming.revision !== current?.revision
      ) {
        // Subscription delivery can lag behind a mutation response. Older
        // notifications are stale, not collaborative edits.
        if (
          current?.revision !== null &&
          current?.revision !== undefined &&
          incoming.revision !== null &&
          incoming.revision < current.revision
        ) {
          return event;
        }
        if (draftDirtyRef.current || answerDirtyRef.current) {
          setSaveState("conflict");
          setConflictAt(current?.revision ?? null);
          setConflictCurrentRevision(incoming.revision);
          return event;
        }
        refetch({ requestPolicy: "network-only" });
      }
      return event;
    },
  );

  const [, executeAnswer] = useMutation(SUBMIT_AUTHORING_ANSWER_MUTATION);
  const [, executeReplan] = useMutation<ReplanAuthoringData>(REPLAN_AUTHORING_MUTATION);
  const [, executeAction] = useMutation(SELECT_AUTHORING_ACTION_MUTATION);
  const [, executeRevise] = useMutation(REVISE_AUTHORING_COVERAGE_MUTATION);
  const [, executeReviseSection] = useMutation(REVISE_AUTHORING_SECTION_MUTATION);
  const [, executeReviseDocument] = useMutation(REVISE_AUTHORING_DOCUMENT_MUTATION);
  const [, executeReviewComments] = useMutation(SUBMIT_AUTHORING_REVIEW_COMMENTS_MUTATION);
  const [, executeAddReviewComment] = useMutation(ADD_AUTHORING_REVIEW_COMMENT_MUTATION);
  const [, executePrepareCommit] =
    useMutation<PrepareAuthoringCommitData>(PREPARE_AUTHORING_COMMIT_MUTATION);
  const [, executePublish] =
    useMutation<PublishAuthoringDraftData>(PUBLISH_AUTHORING_DRAFT_MUTATION);

  const failMutation = useCallback((message: string) => {
    setSaveState("error");
    setMutationError(message);
  }, []);

  const applyResult = useCallback(
    (next: AuthoringSession, answeredQuestionId: string | null) => {
      if (next.status === "revision_conflict") {
        setSaveState("conflict");
        setConflictAt(session?.revision ?? null);
        setConflictCurrentRevision(next.revision);
        setMutationError(null);
        return;
      }
      if (next.status === "error" || next.status === "helper_unavailable") {
        failMutation(next.message || "The interview update could not be saved.");
        return;
      }
      setConflictAt(null);
      setConflictCurrentRevision(null);
      setSaveState("saved");
      setMutationError(null);
      setEditingCoverageId(null);
      setEditingCoverageAnswer("");
      setAnswerDirty(false);
      answerDirtyRef.current = false;
      setDraftText("");
      sessionRef.current = next;
      setSession(next);
      if (next.featureName && next.featureName !== featureName) {
        router.replace(`/define/${next.featureName}/authoring/${artifactType}`);
      }
      if (answeredQuestionId) {
        setHighlightQuestionId(answeredQuestionId);
        window.setTimeout(() => setHighlightQuestionId(null), 1240);
      }
    },
    [artifactType, failMutation, featureName, router, session?.revision],
  );

  const guard = useCallback(
    async <T,>(run: () => Promise<T>): Promise<T | null> => {
      submittingRef.current = true;
      setSaveState("saving");
      setMutationError(null);
      try {
        return await run();
      } catch (err) {
        failMutation(
          err instanceof Error ? err.message : "The interview update could not be saved.",
        );
        return null;
      } finally {
        submittingRef.current = false;
      }
    },
    [failMutation],
  );

  const planningMode = session?.planning?.mode;
  const plannerVersion = session?.planning?.planner_version;
  const expectedPlannerVersion = artifactType === "prd" ? "model-prd-v5" : "model-downstream-v1";
  const sessionRevision = session?.revision ?? null;
  const sessionStatus = session?.status;
  const shouldReplan = Boolean(
    session &&
      sessionRevision !== null &&
      sessionStatus !== "not_started" &&
      sessionStatus !== "helper_unavailable" &&
      sessionStatus !== "drafted" &&
      sessionStatus !== "drafted_with_open_questions" &&
      sessionStatus !== "published" &&
      !(planningMode === "model" && plannerVersion === expectedPlannerVersion),
  );

  // Older checkpoints predate completeness-driven semantic planning. Resume
  // upgrades them once, explicitly, while the
  // read-only session query remains side-effect free.
  useEffect(() => {
    if (!shouldReplan || sessionRevision === null) return;
    const key = `${featureName}:${artifactType}`;
    if (replanAttemptRef.current.has(key)) return;
    replanAttemptRef.current.add(key);
    const requestRoute = `${featureName}:${artifactType}`;
    setReplanning(true);
    submittingRef.current = true;
    setSaveState("saving");
    executeReplan({
      featureName,
      artifactType,
      expectedRevision: sessionRevision,
    }).then((result) => {
      if (!mountedRef.current || routeIdentityRef.current !== requestRoute) return;
      const next = result.data?.replanAuthoring;
      if (result.error || !next) {
        failMutation(result.error?.message ?? "AI planning could not be completed.");
      } else {
        applyResult(next, null);
      }
    }).catch((err: unknown) => {
      if (mountedRef.current && routeIdentityRef.current === requestRoute) {
        failMutation(err instanceof Error ? err.message : "AI planning could not be completed.");
      }
    }).finally(() => {
      if (mountedRef.current && routeIdentityRef.current === requestRoute) {
        setReplanning(false);
        submittingRef.current = false;
      }
    });
  }, [
    applyResult,
    artifactType,
    executeReplan,
    failMutation,
    featureName,
    planningRetry,
    plannerVersion,
    sessionRevision,
    shouldReplan,
  ]);

  const submitAnswer = useCallback(
    async (text: string) => {
      if (!session?.currentQuestion || session.revision === null) return;
      const questionId = session.currentQuestion.id;
      const revision = session.revision;
      const result = await guard(() =>
        executeAnswer({
          featureName,
          artifactType,
          questionId,
          answer: text,
          expectedRevision: revision,
        }),
      );
      if (!result) return;
      const next = result.data?.submitAuthoringAnswer as AuthoringSession | undefined;
      if (result.error || !next) {
        failMutation(result.error?.message ?? "The answer could not be saved.");
        return;
      }
      applyResult(next, questionId);
    },
    [applyResult, artifactType, executeAnswer, failMutation, featureName, guard, session],
  );

  const submitPlannedAnswer = useCallback(
    async ({ question_id, answer }: { question_id: string; answer: string }) => {
      if (!session || session.revision === null) return;
      const result = await guard(() =>
        executeAnswer({
          featureName,
          artifactType,
          questionId: question_id,
          answer,
          expectedRevision: session.revision,
        }),
      );
      if (!result) return;
      const next = result.data?.submitAuthoringAnswer as AuthoringSession | undefined;
      if (result.error || !next) {
        failMutation(result.error?.message ?? "The answer could not be saved.");
        return;
      }
      applyResult(next, question_id);
    },
    [
      applyResult,
      artifactType,
      executeAnswer,
      failMutation,
      featureName,
      guard,
      session,
    ],
  );

  const submitAction = useCallback(
    async (action: AuthoringAction) => {
      if (!session || session.revision === null) return;
      const questionId = session.currentQuestion?.id ?? null;
      const revision = session.revision;
      const result = await guard(() =>
        executeAction({ featureName, artifactType, action, expectedRevision: revision }),
      );
      if (!result) return;
      const next = result.data?.selectAuthoringAction as AuthoringSession | undefined;
      if (result.error || !next) {
        failMutation(result.error?.message ?? "The selected action could not be saved.");
        return;
      }
      applyResult(
        next,
        action === "EDIT" ? null : questionId,
      );
    },
    [applyResult, artifactType, executeAction, failMutation, featureName, guard, session],
  );

  const beginCoverageEdit = useCallback((coverageId: string, answer?: string) => {
    const source = session?.sections?.find((section) =>
      [...(section.coverage_ids ?? []), ...(section.question_ids ?? [])].includes(coverageId),
    );
    setEditingCoverageId(coverageId);
    setEditingCoverageAnswer(
      answer ?? source?.source_answers?.[coverageId] ?? source?.source_answer ?? "",
    );
    setMutationError(null);
  }, [session?.sections]);

  const submitCoverageRevision = useCallback(
    async (answer: string) => {
      if (!session || session.revision === null || !editingCoverageId) return;
      const result = await guard(() =>
        executeRevise({
          featureName,
          artifactType,
          coverageId: editingCoverageId,
          answer,
          expectedRevision: session.revision as number,
        }),
      );
      if (!result) return;
      const next = result.data?.reviseAuthoringCoverage as AuthoringSession | undefined;
      if (result.error || !next) {
        failMutation(result.error?.message ?? `The ${artifactLabel} revision could not be saved.`);
        return;
      }
      applyResult(next, editingCoverageId);
    },
    [
      applyResult,
      artifactLabel,
      artifactType,
      editingCoverageId,
      executeRevise,
      failMutation,
      featureName,
      guard,
      session,
    ],
  );

  const submitDraftSectionRevision = useCallback(
    async (sectionTitle: string, body: string): Promise<boolean> => {
      if (!session || session.revision === null) return false;
      const result = await guard(() =>
        executeReviseSection({
          featureName,
          artifactType,
          sectionTitle,
          body,
          expectedRevision: session.revision as number,
        }),
      );
      if (!result) return false;
      const next = result.data?.reviseAuthoringSection as AuthoringSession | undefined;
      if (result.error || !next) {
        failMutation(result.error?.message ?? `The ${artifactLabel} section could not be saved.`);
        return false;
      }
      applyResult(next, null);
      return next.status !== "error" && next.status !== "revision_conflict";
    },
    [
      applyResult,
      artifactLabel,
      artifactType,
      executeReviseSection,
      failMutation,
      featureName,
      guard,
      session,
    ],
  );

  const submitDraftDocumentRevision = useCallback(
    async (content: string): Promise<boolean> => {
      if (!session || session.revision === null) return false;
      const result = await guard(() => executeReviseDocument({
        featureName,
        artifactType,
        content,
        expectedRevision: session.revision,
      }));
      if (!result) return false;
      const next = result.data?.reviseAuthoringDocument as AuthoringSession | undefined;
      if (result.error || !next) {
        failMutation(result.error?.message ?? `The ${artifactLabel} could not be saved.`);
        return false;
      }
      applyResult(next, null);
      return !["error", "revision_conflict"].includes(next.status);
    },
    [applyResult, artifactLabel, artifactType, executeReviseDocument, failMutation, featureName, guard, session],
  );

  const pendingComments = (session?.reviewComments ?? []).filter(
    (comment) => !comment.status || comment.status === "open",
  );

  const addReviewComment = useCallback(async (sectionTitle: string, comment: string, anchor?: { selected_text: string; selection_start: number; selection_end: number; anchor_revision: number }) => {
    if (!session || session.revision === null) return;
    const result = await guard(() => executeAddReviewComment({
      featureName,
      artifactType,
      comment: { section_title: sectionTitle, comment, ...anchor },
      expectedRevision: session.revision,
    }));
    if (!result) return;
    const next = result.data?.addAuthoringReviewComment as AuthoringSession | undefined;
    if (result.error || !next) {
      failMutation(result.error?.message ?? "The review comment could not be saved.");
      return;
    }
    applyResult(next, null);
  }, [applyResult, artifactType, executeAddReviewComment, failMutation, featureName, guard, session]);

  const regenerateFromComments = useCallback(async () => {
    if (!session || session.revision === null || pendingComments.length === 0) return;
    const result = await guard(() =>
      executeReviewComments({
        featureName,
        artifactType,
        comments: pendingComments,
        expectedRevision: session.revision as number,
      }),
    );
    if (!result) return;
    const next = result.data?.submitAuthoringReviewComments as AuthoringSession | undefined;
    if (result.error || !next) {
      failMutation(
        result.error?.message ??
          `The ${artifactLabel} could not be regenerated from the review comments.`,
      );
      return;
    }
    applyResult(next, null);
  }, [
    applyResult,
    artifactLabel,
    artifactType,
    executeReviewComments,
    failMutation,
    featureName,
    guard,
    pendingComments,
    session,
  ]);

  useEffect(() => {
    if (questionColumnRef.current) questionColumnRef.current.scrollTop = 0;
  }, [editingCoverageId, session?.currentQuestion?.id, session?.status]);

  const reviewAndCommit = useCallback(async () => {
    setPreparingCommit(true);
    setMutationError(null);
    try {
      const result = await executePrepareCommit({ featureName, artifactType });
      if (result.error || !result.data?.prepareAuthoringCommit) {
        setMutationError(
          result.error?.message ?? `The ${artifactLabel} could not be prepared for review and commit.`,
        );
        return;
      }
      // The author has already reviewed the context and the generated PRD in
      // this flow. Skip the generic BLUF interstitial so the explicit
      // "Review & commit" action opens the existing commit workspace directly.
      window.localStorage.setItem(`bluf-dismissed-${featureName}`, "true");
      router.push(`/define/${featureName}`);
    } catch (err) {
      setMutationError(
        err instanceof Error
          ? err.message
          : `The ${artifactLabel} could not be prepared for review and commit.`,
      );
    } finally {
      setPreparingCommit(false);
    }
  }, [artifactLabel, artifactType, executePrepareCommit, featureName, router]);

  const publishDraft = useCallback(async (): Promise<boolean> => {
    if (!session || session.revision === null) return false;
    setPublishing(true);
    const result = await guard(() => executePublish({
      featureName,
      artifactType,
      expectedRevision: session.revision,
    }));
    setPublishing(false);
    if (!result) return false;
    const next = result.data?.publishAuthoringDraft;
    if (result.error || !next) {
      failMutation(result.error?.message ?? "The draft could not be published.");
      return false;
    }
    applyResult(next, null);
    return next.status === "published";
  }, [applyResult, artifactType, executePublish, failMutation, featureName, guard, session]);

  if (error) {
    return (
      <Shell>
        <div className="surface" style={{ padding: 20, margin: 24 }}>
          <div className="type-section-title">The dashboard API is unreachable</div>
          <div className="type-body" style={{ marginTop: 8 }}>
            {error.message}
          </div>
        </div>
      </Shell>
    );
  }

  if (!session) {
    return (
      <Shell>
        <div style={{ padding: 24, opacity: fetching || !subscribed ? 0.4 : 1 }}>
          <div className="type-body">Loading the interview…</div>
        </div>
      </Shell>
    );
  }

  if (session.status === "helper_unavailable") {
    return (
      <Shell>
        <div style={{ padding: 24, maxWidth: 640 }}>
          <HelperUnavailable
            message={session.message}
            helperPath={session.helperPath}
            interpreter={session.interpreter}
            onRetry={() => refetch({ requestPolicy: "network-only" })}
          />
        </div>
      </Shell>
    );
  }

  if (session.status === "not_started") {
    return (
      <Shell>
        <div className="surface" style={{ padding: 20, margin: 24, maxWidth: 560 }}>
          <div className="type-section-title">No interview yet</div>
          <div className="type-body" style={{ marginTop: 8 }}>
            {session.message}
          </div>
          <button
            type="button"
            className="type-badge"
            onClick={() => router.push("/define/new")}
            style={{
              marginTop: 16,
              height: 32,
              padding: "0 16px",
              border: "none",
              borderRadius: 6,
              background: "var(--color-accent)",
              color: "var(--color-bg)",
              cursor: "pointer",
            }}
          >
            Start an artifact
          </button>
        </div>
      </Shell>
    );
  }

  const terminal = ["drafted", "published", "review_repair"].includes(session.status);
  const showDraftPreview = Boolean(
    terminal && session.draftAvailable && session.artifactContent,
  );
  const plannedQuestions = session.planning?.questions ?? [];
  const hasDerivedTitle =
    artifactType !== "prd" ||
    Boolean(session.intake?.feature_title && session.featureTitle);
  const showPlannedInterview =
    session.planning?.mode === "model" &&
    plannedQuestions.length > 0 &&
    (session.interview?.length ?? 0) === 0 &&
    plannedQuestions.every(
      (question) => question.response_control.submit_action === "answer",
    ) &&
    Boolean(session.currentQuestion) &&
    !session.currentQuestion?.follow_up &&
    !session.currentQuestion?.edit_request &&
    (session.currentQuestion?.review_findings?.length ?? 0) === 0;

  return (
    <Shell>
      <AuthoringBar
        session={session}
        saveState={(draftDirty || answerDirty) && saveState === "saved" ? "unsaved" : saveState}
      />
      {saveState === "conflict" && conflictAt !== null && (
        <ConflictBanner
          heldRevision={conflictAt}
          currentRevision={conflictCurrentRevision}
          onReload={() => {
            setSaveState("saved");
            setConflictAt(null);
            setConflictCurrentRevision(null);
            draftDirtyRef.current = false;
            answerDirtyRef.current = false;
            setDraftDirty(false);
            setAnswerDirty(false);
            setDraftText("");
            setDraftResetKey((current) => current + 1);
            setAnswerResetKey((current) => current + 1);
            refetch({ requestPolicy: "network-only" });
          }}
        />
      )}
      {mutationError && (
        <div
          role="alert"
          style={{
            padding: "10px 24px",
            color: "var(--color-red)",
            background: "rgba(239, 68, 100, 0.08)",
            borderBottom: "1px solid rgba(239, 68, 100, 0.2)",
            fontSize: 12,
            fontWeight: 500,
          }}
        >
          {mutationError} Any entered answer or pending review comment remains on this
          page so you can retry.
        </div>
      )}
      {session.planning?.mode === "fallback" &&
        session.planning?.planner_version === expectedPlannerVersion &&
        !replanning && (
        <div
          role="status"
          style={{
            padding: "10px 24px",
            color: "var(--color-amber)",
            background: "rgba(245, 158, 11, 0.08)",
            borderBottom: "1px solid rgba(245, 158, 11, 0.2)",
            fontSize: 12,
          }}
        >
          AI planning is unavailable; fallback questions are active. {session.planning.fallback_reason}
          {shouldReplan && (
            <button
              type="button"
              onClick={() => {
                replanAttemptRef.current.delete(`${featureName}:${artifactType}`);
                setPlanningRetry((current) => current + 1);
              }}
              style={{
                marginLeft: 12,
                border: "1px solid var(--color-amber)",
                borderRadius: 5,
                background: "transparent",
                color: "var(--color-amber)",
                padding: "4px 9px",
                cursor: "pointer",
              }}
            >
              Retry AI planning
            </button>
          )}
        </div>
      )}
      <div
        className="guided-authoring-layout"
        style={{
          flex: 1,
          display: "flex",
          gap: 0,
          padding: 0,
          overflow: "hidden",
          alignItems: "stretch",
        }}
      >
        <div
          ref={questionColumnRef}
          className="guided-authoring-question"
          style={{
            flex: showDraftPreview ? "0 0 40%" : "1 1 100%",
            minWidth: 360,
            overflowY: "auto",
            display: "flex",
            flexDirection: "column",
            gap: 16,
            padding: 24,
            borderRight: showDraftPreview ? "1px solid var(--color-border)" : "none",
          }}
        >
          <div style={{ maxWidth: showDraftPreview ? 560 : 720, width: "100%", margin: "0 auto", display: "flex", flexDirection: "column", gap: 18 }}>
            {session.intake?.feature_description && (
              <div>
                <div className="type-caption" style={{ marginBottom: 7, color: "var(--color-text-secondary)" }}>You</div>
                <div style={{ marginLeft: 30, padding: "13px 14px", borderRadius: 9, background: "var(--color-bg-card)", border: "1px solid var(--color-border)", color: "var(--color-text-secondary)", lineHeight: 1.55 }}>
                  {session.intake.feature_description}
                </div>
              </div>
            )}
            {hasDerivedTitle && (
              <div>
                <div className="type-caption" style={{ marginBottom: 7, color: "var(--color-accent)" }}>SPEED Assistant</div>
                <div className="type-body" style={{ marginLeft: 30, lineHeight: 1.6 }}>
                  <div>Title: <span style={{ color: "var(--color-accent)" }}>{session.featureTitle}</span></div>
                  {session.planning?.analysis_summary && <div style={{ marginTop: 8 }}>{session.planning.analysis_summary}</div>}
                </div>
              </div>
            )}
            {replanning ? (
              <div className="surface" role="status" style={{ padding: 20 }}>
                <div className="type-compact-label">Analyzing with AI</div>
                <div className="type-section-title" style={{ marginTop: 10 }}>
                  Deriving the title and planning your {artifactLabel} interview…
                </div>
                <div className="type-body" style={{ marginTop: 8 }}>
                  The configured planning model is checking every PRD section and identifying all material decisions that still need your input.
                </div>
              </div>
            ) : editingCoverageId ? (
              <CoverageEditCard
                questionId={editingCoverageId}
                initialAnswer={editingCoverageAnswer}
                submitting={saveState === "saving"}
                onCancel={() => {
                  setEditingCoverageId(null);
                  setEditingCoverageAnswer("");
                }}
                onSubmit={submitCoverageRevision}
              />
            ) : terminal ? (
              <>
                <AnswerReviewCarousel
                  answers={session.interview ?? []}
                  onEditAnswer={(questionId, answer) =>
                    beginCoverageEdit(questionId, answer)
                  }
                />
                <SelfReviewSummary
                  session={session}
                  onEditQuestion={beginCoverageEdit}
                  artifactLabel={artifactLabel}
                  pendingCommentCount={pendingComments.length}
                  regenerating={saveState === "saving"}
                  onRegenerate={regenerateFromComments}
                />
              </>
            ) : (
              <>
                {showPlannedInterview && (
                  <QuestionBatch
                    key={`${session.revision}:${answerResetKey}`}
                    questions={plannedQuestions}
                    revision={session.revision as number}
                    submitting={saveState === "saving"}
                    onSubmit={submitPlannedAnswer}
                    artifactLabel={artifactLabel}
                    onDirtyChange={setAnswerDirty}
                  />
                )}
                {!showPlannedInterview && session.currentQuestion && session.revision !== null && (
                  <QuestionCard
                    key={`${session.currentQuestion.id}:${answerResetKey}`}
                    question={session.currentQuestion}
                    revision={session.revision}
                    submitting={saveState === "saving"}
                    draftText={draftText}
                    onDraftTextChange={setDraftText}
                    onDirtyChange={setAnswerDirty}
                    onAction={submitAction}
                    onAnswer={submitAnswer}
                    position={Math.min(session.progress.confirmed + 1, session.progress.total)}
                    total={session.progress.total}
                    answerButtonLabel={
                      session.progress.confirmed + 1 >= session.progress.total
                        ? `Generate ${artifactLabel}`
                        : "Save & continue"
                    }
                    submittingButtonLabel={
                      session.progress.confirmed + 1 >= session.progress.total
                        ? `Generating ${artifactLabel}…`
                        : "Saving…"
                    }
                  />
                )}
              </>
            )}
            {session.status === "blocked" && (
              <BlockingNotice
                message={session.message}
                deferred={session.progress.deferred}
              />
            )}
            {terminal && (
              <div style={{ marginTop: "auto", paddingTop: 10 }}>
                <textarea aria-label={`Ask for a ${artifactLabel} change`} value={globalFeedback} onChange={(event) => setGlobalFeedback(event.target.value)} placeholder="Ask for a change or add an edge case…"
                  style={{ width: "100%", minHeight: 92, resize: "vertical", padding: 12, borderRadius: 8, border: "1px solid var(--color-border)", background: "var(--color-bg-elevated)", color: "var(--color-text)" }} />
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginTop: 8 }}>
                  <span className="type-caption">{pendingComments.length ? `${pendingComments.length} change${pendingComments.length === 1 ? "" : "s"} queued` : "Broad feedback can update one or more sections."}</span>
                  <button type="button" className="type-badge" disabled={globalFeedback.trim().length < 3} onClick={() => { addReviewComment("__document__", globalFeedback.trim()); setGlobalFeedback(""); }}
                    style={{ border: 0, borderRadius: 5, padding: "8px 12px", background: "var(--color-accent)", color: "var(--color-bg)", opacity: globalFeedback.trim().length < 3 ? .4 : 1 }}>Add to review</button>
                </div>
              </div>
            )}
          </div>
        </div>
        {showDraftPreview && session.artifactContent && (
          <DraftPreview
            key={draftResetKey}
            content={session.artifactContent}
            sections={session.sections ?? []}
            artifactPath={session.artifactPath}
            revision={session.revision}
            highlightQuestionId={highlightQuestionId}
            onEditDraftSection={submitDraftSectionRevision}
            onSaveDocument={submitDraftDocumentRevision}
            onDirtyChange={setDraftDirty}
            saving={saveState === "saving"}
            expanded
            comments={pendingComments}
            onAddComment={addReviewComment}
            versions={session.versions ?? []}
            artifactType={artifactType}
            artifactLabel={artifactLabel}
            publishedRevision={session.publishedRevision}
            publishing={publishing}
            onPublish={session.status === "review_repair" ? undefined : publishDraft}
            preparingCommit={preparingCommit}
            onReviewCommit={session.status === "review_repair" ? undefined : reviewAndCommit}
          />
        )}
      </div>
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", height: "100vh" }}>
      <IconRail />
      <div
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        <Header />
        <ErrorBoundary>
          <main
            style={{
              flex: 1,
              display: "flex",
              flexDirection: "column",
              overflow: "hidden",
            }}
          >
            {children}
          </main>
        </ErrorBoundary>
      </div>
    </div>
  );
}
