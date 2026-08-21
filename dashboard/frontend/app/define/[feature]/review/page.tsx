"use client";

import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation } from "urql";
import {
  CEREMONY_INFO_QUERY,
  type CeremonyInfoData,
} from "@/lib/graphql/queries/ceremony";
import {
  COMMIT_RECORD_QUERY,
  RATIFICATION_STATE_QUERY,
  SUBMIT_RATIFICATION_MUTATION,
  type CommitRecordData,
  type CommitRecordVars,
  type RatificationStateData,
  type RatificationStateVars,
  type SubmitRatificationData,
  type SubmitRatificationVars,
} from "@/lib/graphql/queries/ceremony-commitment";
import {
  ALL_SPEC_DRAFTS_QUERY,
  type AllSpecDraftsData,
  type AllSpecDraftsVars,
} from "@/lib/graphql/queries/ceremony-editor";
import { ErrorBoundary } from "@/components/shared/error-boundary";
import { IconRail } from "@/components/landing/IconRail";
import { Header } from "@/components/layout/header";
import { SpecPreview } from "@/components/editor/SpecPreview";
import { RatificationSummary } from "@/components/ceremony/RatificationSummary";
import { RatificationControls } from "@/components/ceremony/RatificationControls";

/**
 * Route: /define/:feature/review
 * Ratification view. Shows read-only spec on the left,
 * evidence panel with approve/reject on the right.
 * In SP mode, redirects to /define/:feature.
 */
export default function DefineFeatureReviewPage() {
  const params = useParams<{ feature: string }>();
  const router = useRouter();
  const featureName = params.feature;

  const [{ data: ceremonyData, fetching: fetchingCeremony }] = useQuery<CeremonyInfoData>({
    query: CEREMONY_INFO_QUERY,
    variables: { featureName },
  });

  // The /review route currently shows only the PRD commit record and
  // ratification state. Per-spec ratification on the main ceremony page
  // replaces this flow; the design spec marks /review as superseded.
  // Until the main page ships ratification inline, pin specType to "prd".
  const [{ data: commitData }] = useQuery<CommitRecordData, CommitRecordVars>({
    query: COMMIT_RECORD_QUERY,
    variables: { featureName, specType: "prd" },
  });

  const [{ data: ratData }, reexecuteRat] = useQuery<RatificationStateData, RatificationStateVars>({
    query: RATIFICATION_STATE_QUERY,
    variables: { featureName, specType: "prd" },
  });

  const [{ data: draftsData }] = useQuery<AllSpecDraftsData, AllSpecDraftsVars>({
    query: ALL_SPEC_DRAFTS_QUERY,
    variables: { featureName },
  });

  const [, executeRatification] = useMutation<SubmitRatificationData, SubmitRatificationVars>(
    SUBMIT_RATIFICATION_MUTATION
  );

  // SP redirect
  useEffect(() => {
    if (fetchingCeremony) return;
    if (ceremonyData?.ceremonyInfo && !ceremonyData.ceremonyInfo.isMultiplayer) {
      router.replace(`/define/${featureName}`);
    }
  }, [fetchingCeremony, ceremonyData, featureName, router]);

  const ceremony = ceremonyData?.ceremonyInfo;
  const commitRecord = commitData?.commitRecord;
  const ratState = ratData?.ratificationState;
  const prdDraft = draftsData?.allSpecDrafts?.find((d) => d.specType === "prd");
  const specContent = prdDraft?.content ?? "";

  const revStatus = ceremony?.currentRevision?.status;
  const isRatified = ratState?.status === "ratified";
  const isRejected = ratState?.status === "rejected";

  const handleApprove = async () => {
    await executeRatification({ featureName, specType: "prd", verdict: "approve" });
    reexecuteRat({ requestPolicy: "network-only" });
  };

  const handleReject = async (comment: string) => {
    await executeRatification({ featureName, specType: "prd", verdict: "reject", comment });
    reexecuteRat({ requestPolicy: "network-only" });
  };

  if (!fetchingCeremony && ceremony && revStatus !== "COMMITTED" && revStatus !== "RATIFIED" && revStatus !== "REJECTED") {
    return (
      <div style={{ display: "flex", height: "100vh" }}>
        <IconRail />
        <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <span style={{ fontSize: 13, color: "var(--color-text-tertiary)" }}>
            This spec is not ready for review (status: {revStatus ?? "unknown"})
          </span>
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", height: "100vh" }}>
      <IconRail />
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <Header />

        {/* Status banner */}
        {isRatified && (
          <div style={{
            padding: "8px 20px", fontSize: 12, fontWeight: 600,
            background: "rgba(68, 204, 119, 0.1)", color: "var(--color-emerald)",
            borderBottom: "1px solid rgba(68, 204, 119, 0.2)",
            display: "flex", alignItems: "center", gap: 8,
          }}>
            Ratified
          </div>
        )}
        {isRejected && (
          <div style={{
            padding: "8px 20px", fontSize: 12, fontWeight: 600,
            background: "rgba(239, 68, 100, 0.1)", color: "var(--color-red)",
            borderBottom: "1px solid rgba(239, 68, 100, 0.2)",
            display: "flex", alignItems: "center", gap: 8,
          }}>
            Rejected
            {ratState?.verdicts?.find((v) => v.verdict === "reject")?.comment && (
              <span style={{ fontWeight: 400, color: "var(--color-text-secondary)" }}>
                — {ratState.verdicts.find((v) => v.verdict === "reject")?.comment}
              </span>
            )}
          </div>
        )}

        <main style={{ flex: 1, display: "flex", overflow: "hidden" }}>
          <ErrorBoundary>
            {/* Left: read-only spec */}
            <div style={{ flex: 1, overflow: "auto", borderRight: "1px solid var(--color-border)" }}>
              <div style={{
                padding: "8px 20px", fontSize: 10, fontWeight: 500,
                fontFamily: "var(--font-mono)", color: "var(--color-text-tertiary)",
                textTransform: "uppercase", letterSpacing: "0.05em",
                borderBottom: "1px solid var(--color-border-light)",
              }}>
                Read-only
              </div>
              <div style={{ padding: 20 }}>
                <SpecPreview content={specContent} />
              </div>
            </div>

            {/* Right: evidence panel */}
            <div style={{
              width: 320, flexShrink: 0, overflow: "auto", padding: 20,
              display: "flex", flexDirection: "column", gap: 16,
              background: "var(--color-bg-elevated)",
            }}>
              {commitRecord && ratState && (
                <>
                  <RatificationSummary
                    commitRecord={commitRecord}
                    ratificationState={ratState}
                  />
                  <div style={{ marginTop: "auto" }}>
                    <RatificationControls
                      onApprove={handleApprove}
                      onReject={handleReject}
                      disabled={isRatified || isRejected}
                      hasVoted={ratState.hasVoted}
                      isAuthor={ratState.isAuthor}
                    />
                  </div>
                </>
              )}
            </div>
          </ErrorBoundary>
        </main>
      </div>
    </div>
  );
}
