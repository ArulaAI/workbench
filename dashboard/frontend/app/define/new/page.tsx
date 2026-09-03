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
  ArtifactChoice,
  DesignBranchNotice,
  GuidedPrdIntakeForm,
} from "@/components/ceremony/guided";
import {
  BOOTSTRAP_STATUS_QUERY,
  type BootstrapStatusData,
} from "@/lib/graphql/queries/ceremony-bootstrap";
import {
  AUTHORING_INTAKE_QUERY,
  AUTHORING_SESSION_QUERY,
  START_AUTHORING_MUTATION,
  type AuthoringIntakeData,
  type AuthoringSessionData,
  type StartAuthoringData,
} from "@/lib/graphql/queries/authoring";

type Branch = "choose" | "prd" | "design" | "ceremony";

/**
 * Route: /define/new
 * Bootstrap first. Then the artifact choice returned by the interview helper:
 * PRD opens the guided intake form, Design points at the CLI. The intent-first
 * ceremony remains reachable as dashboard navigation, not as an interview
 * option the helper did not offer.
 */
export default function DefineNewPage() {
  const router = useRouter();
  const [branch, setBranch] = useState<Branch>("choose");
  const [slug, setSlug] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);

  const [{ data: bootstrapData, fetching: bootstrapFetching }] =
    useQuery<BootstrapStatusData>({ query: BOOTSTRAP_STATUS_QUERY });

  const [{ data: intakeData, fetching: intakeFetching }] = useQuery<AuthoringIntakeData>({
    query: AUTHORING_INTAKE_QUERY,
    variables: { artifactType: branch === "prd" ? "prd" : null },
  });

  const [{ data: existing }] = useQuery<AuthoringSessionData>({
    query: AUTHORING_SESSION_QUERY,
    variables: { featureName: slug, artifactType: "prd" },
    pause: slug.length === 0,
    requestPolicy: "network-only",
  });

  const [, executeStart] = useMutation<StartAuthoringData>(START_AUTHORING_MUTATION);

  const start = useCallback(
    async (title: string, featureSlug: string, description: string) => {
      setSubmitting(true);
      setServerError(null);
      try {
        const result = await executeStart({
          featureName: featureSlug,
          featureTitle: title,
          featureDescription: description,
        });
        const session = result.data?.startAuthoring;
        if (!session || result.error) {
          setServerError(result.error?.message ?? "The interview could not be started.");
          return;
        }
        if (
          session.status === "error" ||
          session.status === "helper_unavailable" ||
          session.status === "multiplayer_unsupported"
        ) {
          setServerError(session.message);
          return;
        }
        router.push(`/define/${featureSlug}/authoring/prd`);
      } finally {
        setSubmitting(false);
      }
    },
    [executeStart, router],
  );

  const needsBootstrap = bootstrapData?.bootstrapStatus?.needsBootstrap ?? false;

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
            {bootstrapFetching ? null : needsBootstrap ? (
              <BootstrapWizard onComplete={() => window.location.reload()} />
            ) : branch === "ceremony" ? (
              <IntentInput />
            ) : branch === "design" ? (
              <DesignBranchNotice onBack={() => setBranch("choose")} />
            ) : branch === "prd" ? (
              intakeData?.authoringIntake?.nextInput ? (
                <GuidedPrdIntakeForm
                  input={intakeData.authoringIntake.nextInput}
                  submitting={submitting}
                  existingStatus={existing?.authoringSession?.status ?? null}
                  serverError={serverError}
                  onSlugChange={setSlug}
                  onSubmit={start}
                  onResume={(featureSlug) =>
                    router.push(`/define/${featureSlug}/authoring/prd`)
                  }
                />
              ) : null
            ) : intakeFetching ? null : intakeData?.authoringIntake?.nextInput ? (
              <ArtifactChoice
                input={intakeData.authoringIntake.nextInput}
                onSelect={(value) => setBranch(value === "design" ? "design" : "prd")}
              />
            ) : (
              <IntentInput />
            )}
          </ErrorBoundary>

          {!needsBootstrap && branch === "choose" && (
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
