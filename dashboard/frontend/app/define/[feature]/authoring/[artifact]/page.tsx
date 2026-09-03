"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQuery, useSubscription } from "urql";
import { ErrorBoundary } from "@/components/shared/error-boundary";
import { IconRail } from "@/components/landing/IconRail";
import { Header } from "@/components/layout/header";
import {
  AuthoringBar,
  BlockingNotice,
  ConflictBanner,
  CoverageRail,
  DraftPreview,
  HelperUnavailable,
  QuestionCard,
  SelfReviewSummary,
  type SaveState,
} from "@/components/ceremony/guided";
import {
  AUTHORING_SESSION_CHANGED_SUBSCRIPTION,
  AUTHORING_SESSION_QUERY,
  REVISE_AUTHORING_COVERAGE_MUTATION,
  SELECT_AUTHORING_ACTION_MUTATION,
  SUBMIT_AUTHORING_ANSWER_MUTATION,
  type AuthoringAction,
  type AuthoringSession,
  type AuthoringSessionChangedData,
  type AuthoringSessionData,
} from "@/lib/graphql/queries/authoring";

/**
 * Route: /define/:feature/authoring/:artifact
 *
 * Three regions: coverage, current question, generated draft. Every question,
 * option, and message is rendered from the helper payload; this page owns
 * layout, revision discipline, and nothing else.
 */
export default function AuthoringPage() {
  const params = useParams<{ feature: string; artifact: string }>();
  const router = useRouter();
  const featureName = params.feature;
  const artifactType = params.artifact ?? "prd";

  const [session, setSession] = useState<AuthoringSession | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("saved");
  const [conflictAt, setConflictAt] = useState<number | null>(null);
  const [draftText, setDraftText] = useState("");
  const [highlightQuestionId, setHighlightQuestionId] = useState<string | null>(null);
  const submittingRef = useRef(false);

  const [{ data, fetching, error }, refetch] = useQuery<AuthoringSessionData>({
    query: AUTHORING_SESSION_QUERY,
    variables: { featureName, artifactType },
    requestPolicy: "network-only",
  });

  useEffect(() => {
    if (data?.authoringSession) setSession(data.authoringSession);
  }, [data]);

  // A checkpoint written by the CLI or another tab refreshes the view, but
  // never while this tab has a mutation in flight.
  useSubscription<AuthoringSessionChangedData>(
    { query: AUTHORING_SESSION_CHANGED_SUBSCRIPTION, variables: { feature: featureName } },
    (_prev, event) => {
      const incoming = event?.authoringSessionChanged;
      if (
        incoming &&
        incoming.artifactType === artifactType &&
        !submittingRef.current &&
        incoming.revision !== session?.revision
      ) {
        refetch({ requestPolicy: "network-only" });
      }
      return event;
    },
  );

  const [, executeAnswer] = useMutation(SUBMIT_AUTHORING_ANSWER_MUTATION);
  const [, executeAction] = useMutation(SELECT_AUTHORING_ACTION_MUTATION);
  const [, executeRevise] = useMutation(REVISE_AUTHORING_COVERAGE_MUTATION);

  const applyResult = useCallback(
    (next: AuthoringSession | undefined, answeredQuestionId: string | null) => {
      if (!next) {
        setSaveState("saved");
        return;
      }
      if (next.status === "revision_conflict") {
        setSaveState("conflict");
        setConflictAt(session?.revision ?? null);
        return;
      }
      setConflictAt(null);
      setSaveState("saved");
      setSession(next);
      if (answeredQuestionId) {
        setHighlightQuestionId(answeredQuestionId);
        window.setTimeout(() => setHighlightQuestionId(null), 1240);
      }
    },
    [session?.revision],
  );

  const guard = async <T,>(run: () => Promise<T>): Promise<T> => {
    submittingRef.current = true;
    setSaveState("saving");
    try {
      return await run();
    } finally {
      submittingRef.current = false;
    }
  };

  const submitAnswer = useCallback(
    async (text: string) => {
      if (!session?.currentQuestion || session.revision === null) return;
      const questionId = session.currentQuestion.id;
      const revision = session.revision;
      const result = await guard(() =>
        executeAnswer({
          featureName,
          answer: text,
          expectedRevision: revision,
        }),
      );
      applyResult(result.data?.submitAuthoringAnswer, questionId);
    },
    [applyResult, executeAnswer, featureName, session],
  );

  const submitAction = useCallback(
    async (action: AuthoringAction) => {
      if (!session || session.revision === null) return;
      const questionId = session.currentQuestion?.id ?? null;
      const revision = session.revision;
      const result = await guard(() =>
        executeAction({ featureName, action, expectedRevision: revision }),
      );
      applyResult(
        result.data?.selectAuthoringAction,
        action === "EDIT" ? null : questionId,
      );
    },
    [applyResult, executeAction, featureName, session],
  );

  const reviseCoverage = useCallback(
    async (coverageId: string) => {
      if (!session || session.revision === null) return;
      const existing =
        session.currentQuestion?.id === coverageId
          ? session.currentQuestion.existing_answer ?? ""
          : "";
      const answer = existing || draftText;
      if (!answer.trim()) {
        // Reopen the question by asking the helper for its current answer.
        const result = await guard(() =>
          executeRevise({
            featureName,
            coverageId,
            answer: " ",
            expectedRevision: session.revision as number,
          }),
        );
        applyResult(result.data?.reviseAuthoringCoverage, null);
        return;
      }
      const result = await guard(() =>
        executeRevise({
          featureName,
          coverageId,
          answer,
          expectedRevision: session.revision as number,
        }),
      );
      applyResult(result.data?.reviseAuthoringCoverage, coverageId);
    },
    [applyResult, draftText, executeRevise, featureName, session],
  );

  const scrollToSection = useCallback(
    (questionId: string) => {
      const section = (session?.sections ?? []).find((entry) =>
        (entry.question_ids ?? []).includes(questionId),
      );
      if (!section) return;
      const id = `section-${section.title.replace(/[^a-zA-Z0-9]+/g, "-").toLowerCase()}`;
      document.getElementById(id)?.scrollIntoView({ block: "start" });
    },
    [session?.sections],
  );

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
        <div style={{ padding: 24, opacity: fetching ? 0.4 : 1 }}>
          <div className="type-body">Loading the interview…</div>
        </div>
      </Shell>
    );
  }

  if (session.status === "helper_unavailable" || session.status === "multiplayer_unsupported") {
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
            Start a PRD
          </button>
        </div>
      </Shell>
    );
  }

  const answerStates: Record<string, string> = {};
  for (const questionId of session.progress.deferred) answerStates[questionId] = "deferred";
  for (const [questionId, entry] of Object.entries(session.coverage ?? {})) {
    if (entry.confidence_label === "confirmed") answerStates[questionId] = "confirmed";
  }

  const terminal =
    session.status === "drafted" || session.status === "drafted_with_open_questions";

  return (
    <Shell>
      <AuthoringBar session={session} saveState={saveState} />
      {saveState === "conflict" && conflictAt !== null && (
        <ConflictBanner
          heldRevision={conflictAt}
          currentRevision={session.revision}
          onReload={() => {
            setSaveState("saved");
            setConflictAt(null);
            refetch({ requestPolicy: "network-only" });
          }}
        />
      )}
      <div
        style={{
          flex: 1,
          display: "flex",
          gap: 16,
          padding: 24,
          overflow: "hidden",
          alignItems: "stretch",
        }}
      >
        <CoverageRail
          coverage={session.coverage ?? {}}
          answers={answerStates}
          activeQuestionId={session.currentQuestion?.id ?? null}
          confirmed={session.progress.confirmed}
          total={session.progress.total}
          onSelectQuestion={scrollToSection}
        />
        <div
          style={{
            flex: 1,
            minWidth: 320,
            overflowY: "auto",
            display: "flex",
            flexDirection: "column",
            gap: 16,
          }}
        >
          <div style={{ maxWidth: 640, display: "flex", flexDirection: "column", gap: 16 }}>
            {terminal ? (
              <SelfReviewSummary session={session} onEditQuestion={reviseCoverage} />
            ) : (
              session.currentQuestion &&
              session.revision !== null && (
                <QuestionCard
                  question={session.currentQuestion}
                  revision={session.revision}
                  submitting={saveState === "saving"}
                  draftText={draftText}
                  onDraftTextChange={setDraftText}
                  onAction={submitAction}
                  onAnswer={submitAnswer}
                />
              )
            )}
            {session.status === "blocked" && (
              <BlockingNotice
                message={session.message}
                deferred={session.progress.deferred}
              />
            )}
            {session.implementation?.helper_hash && (
              <div className="type-caption" title={session.implementation.helper_hash}>
                helper {session.implementation.helper_hash.slice(7, 19)} · bank{" "}
                {(session.implementation.question_bank_hash ?? "").slice(7, 19)}
              </div>
            )}
          </div>
        </div>
        {session.draftAvailable && session.artifactContent && (
          <DraftPreview
            content={session.artifactContent}
            sections={session.sections ?? []}
            artifactPath={session.artifactPath}
            revision={session.revision}
            highlightQuestionId={highlightQuestionId}
            onEditSection={reviseCoverage}
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
