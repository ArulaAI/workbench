"use client";

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery } from "urql";
import { ErrorBoundary } from "@/components/shared/error-boundary";
import { IconRail } from "@/components/landing/IconRail";
import { Header } from "@/components/layout/header";
import { IntentInput } from "@/components/ceremony/IntentInput";
import { BootstrapWizard } from "@/components/ceremony/BootstrapWizard";
import {
  ArtifactSourceIntake,
  ArtifactTabs,
  DraftsInProgress,
  GuidedPrdIntakeForm,
  type GuidedArtifactType,
} from "@/components/ceremony/guided";
import {
  BOOTSTRAP_STATUS_QUERY,
  type BootstrapStatusData,
} from "@/lib/graphql/queries/ceremony-bootstrap";
import {
  AUTHORING_INTAKE_QUERY,
  AUTHORING_SESSIONS_QUERY,
  START_AUTHORING_MUTATION,
  type AuthoringIntakeData,
  type IntakeInput,
  type AuthoringSessionsData,
  type StartAuthoringData,
} from "@/lib/graphql/queries/authoring";

type Branch = GuidedArtifactType | "ceremony";

/**
 * Route: /define/new
 * The artifact choice comes from the interview helper. Repository bootstrap is
 * required only for the legacy intent-first ceremony, not guided PRD drafting:
 * PRD opens the guided intake form, Design points at the CLI. The intent-first
 * ceremony remains reachable as dashboard navigation, not as an interview
 * option the helper did not offer.
 */
export default function DefineNewPage() {
  const router = useRouter();
  const [branch, setBranch] = useState<Branch>("prd");
  const [submitting, setSubmitting] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);

  const [{ data: bootstrapData, fetching: bootstrapFetching }] =
    useQuery<BootstrapStatusData>({ query: BOOTSTRAP_STATUS_QUERY });

  const [{ data: intakeData, fetching: intakeFetching, error: intakeError }] = useQuery<AuthoringIntakeData>({
    query: AUTHORING_INTAKE_QUERY,
    variables: { artifactType: branch === "ceremony" ? null : branch },
    requestPolicy: "network-only",
  });

  // Read-only: --list reads checkpoints and writes nothing.
  const [{ data: draftsData }] = useQuery<AuthoringSessionsData>({
    query: AUTHORING_SESSIONS_QUERY,
    variables: { artifactType: branch === "ceremony" ? "prd" : branch },
    requestPolicy: "network-only",
  });
  const drafts = draftsData?.authoringSessions?.sessions ?? [];

  const [, executeStart] = useMutation<StartAuthoringData>(START_AUTHORING_MUTATION);

  const start = useCallback(
    async (description: string) => {
      setSubmitting(true);
      setServerError(null);
      // An opaque intake route prevents raw description fragments from
      // becoming package identity. Semantic planning replaces this with the
      // server-derived title slug before the first answer is accepted.
      const intakeId = globalThis.crypto?.randomUUID?.().replace(/-/g, "").slice(0, 16)
        ?? Math.random().toString(36).slice(2, 18);
      const featureSlug = `draft-${intakeId}`;
      const fail = (message: string) => {
        setServerError(message);
        setSubmitting(false);
      };
      let result;
      try {
        result = await executeStart({
          featureName: featureSlug,
          featureTitle: null,
          featureDescription: description,
          artifactType: "prd",
        });
      } catch (err) {
        fail(err instanceof Error ? err.message : "The interview could not be started.");
        return;
      }
      const session = result.data?.startAuthoring;
      if (!session || result.error) {
        fail(result.error?.message ?? "The interview could not be started.");
        return;
      }
      if (session.status === "error" || session.status === "helper_unavailable") {
        fail(session.message);
        return;
      }
      // `submitting` stays set so the form is inert through the route change.
      router.push(`/define/${session.featureName ?? featureSlug}/authoring/prd`);
    },
    [executeStart, router],
  );

  const startFromSource = useCallback(async (featureSlug: string) => {
    if (branch === "prd" || branch === "ceremony" || !featureSlug) return;
    setSubmitting(true);
    setServerError(null);
    try {
      const result = await executeStart({
        featureName: featureSlug,
        featureTitle: null,
        featureDescription: null,
        artifactType: branch,
      });
      const session = result.data?.startAuthoring;
      if (result.error || !session || ["error", "helper_unavailable"].includes(session.status)) {
        setServerError(result.error?.message ?? session?.message ?? `The ${branch} interview could not be started.`);
        setSubmitting(false);
        return;
      }
      router.push(`/define/${featureSlug}/authoring/${branch}`);
    } catch (err) {
      setServerError(err instanceof Error ? err.message : `The ${branch} interview could not be started.`);
      setSubmitting(false);
    }
  }, [branch, executeStart, router]);

  const needsBootstrap = bootstrapData?.bootstrapStatus?.needsBootstrap ?? false;
  const sourceInput: IntakeInput = intakeData?.authoringIntake?.nextInput ?? {
    id: "source_prd",
    input_type: "prd_reference",
    prompt: branch === "rfc"
      ? "Which package with published PRD and Design should ground this Technical RFC?"
      : "Which published PRD should ground this Design draft?",
    options: [],
  };

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
        <main
          style={{
            flex: 1,
            overflow: "auto",
            display: "flex",
            flexDirection: "column",
            justifyContent: "center",
            alignItems: "center",
            gap: 16,
            padding: 24,
          }}
        >
          <ErrorBoundary>
            {branch !== "ceremony" && (
              <ArtifactTabs value={branch} onChange={(value) => { setBranch(value); setServerError(null); }} />
            )}
            {branch === "ceremony" ? (
              bootstrapFetching ? null : needsBootstrap ? (
                <BootstrapWizard onComplete={() => window.location.reload()} />
              ) : (
                <IntentInput />
              )
            ) : branch === "prd" ? (
              intakeData?.authoringIntake?.nextInput ? (
                <GuidedPrdIntakeForm
                  input={intakeData.authoringIntake.nextInput}
                  submitting={submitting}
                  serverError={serverError}
                  onSubmit={start}
                />
              ) : null
            ) : intakeFetching ? null : (
              <ArtifactSourceIntake
                input={sourceInput}
                artifactType={branch}
                submitting={submitting}
                serverError={serverError ?? intakeError?.message ?? null}
                onSelect={startFromSource}
              />
            )}
          </ErrorBoundary>

          {branch !== "ceremony" && drafts.length > 0 && (
            <div style={{ maxWidth: 560, width: "100%", marginTop: 8 }}>
              <DraftsInProgress sessions={drafts} heading="Resume a draft" />
            </div>
          )}

          {branch !== "ceremony" && (
            <button
              type="button"
              className="type-caption"
              onClick={() => setBranch("ceremony")}
              style={{
                background: "transparent",
                border: "none",
                color: "var(--color-text-tertiary)",
                cursor: "pointer",
              }}
            >
              Use the intent-first ceremony instead
            </button>
          )}
        </main>
      </div>
    </div>
  );
}
