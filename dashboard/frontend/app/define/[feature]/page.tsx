"use client";

import React, { useState, useCallback, useRef } from "react";
import { useParams } from "next/navigation";
import { useQuery, useMutation } from "urql";
import { ErrorBoundary } from "@/components/shared/error-boundary";
import { IconRail } from "@/components/landing/IconRail";
import { Header } from "@/components/layout/header";
import { BlufView } from "@/components/ceremony/BlufView";
import { ContextPanel } from "@/components/ceremony/ContextPanel";
import { CeremonyLayout } from "@/components/ceremony/CeremonyLayout";
import {
  CONTEXT_PACKAGE_QUERY,
  REFINE_INTENT_MUTATION,
  type ContextPackageData,
  type ContextPackageVars,
  type RefineIntentData,
  type RefineIntentVars,
} from "@/lib/graphql/queries/ceremony-context";
import {
  CEREMONY_INFO_QUERY,
  type CeremonyInfoData,
} from "@/lib/graphql/queries/ceremony";
import { ResumeCard } from "@/components/ceremony/guided";
import {
  AUTHORING_SESSION_QUERY,
  type AuthoringSessionData,
} from "@/lib/graphql/queries/authoring";

const FEATURE_RE = /^[a-z0-9][a-z0-9-]*$/;

function isValidFeatureName(name: string): boolean {
  return name.length > 0 && name.length <= 50 && FEATURE_RE.test(name);
}

export default function DefineFeaturePage() {
  const params = useParams<{ feature: string }>();
  const featureName = params.feature;

  const [blufDismissed, setBlufDismissed] = useState(() => {
    if (typeof window === "undefined") return false;
    return localStorage.getItem(`bluf-dismissed-${featureName}`) === "true";
  });

  const [refining, setRefining] = useState(false);
  const [scopeDiff, setScopeDiff] = useState<{
    filesAdded: number;
    filesRemoved: number;
    defectsDelta: number;
    learningsDelta: number;
  } | null>(null);

  const [{ data: pkgData, fetching: pkgFetching, error: pkgError }, reexecutePkg] =
    useQuery<ContextPackageData, ContextPackageVars>({
      query: CONTEXT_PACKAGE_QUERY,
      variables: { featureName },
      pause: !isValidFeatureName(featureName),
    });

  // Poll for BLUF synthesis completion (summary arrives after initial load)
  const hasSummary = (pkgData?.contextPackage as any)?.blufSummary;
  React.useEffect(() => {
    if (hasSummary || !pkgData?.contextPackage) return;
    const timer = setInterval(() => {
      reexecutePkg({ requestPolicy: "network-only" });
    }, 3000);
    return () => clearInterval(timer);
  }, [hasSummary, pkgData?.contextPackage, reexecutePkg]);

  const [, executeRefine] = useMutation<RefineIntentData, RefineIntentVars>(
    REFINE_INTENT_MUTATION
  );

  // Guided authoring checkpoint, read-only: --peek never creates state.
  const [{ data: authoringData }] = useQuery<AuthoringSessionData>({
    query: AUTHORING_SESSION_QUERY,
    variables: { featureName, artifactType: "prd" },
    pause: !isValidFeatureName(featureName),
    requestPolicy: "network-only",
  });
  const authoring = authoringData?.authoringSession;
  const resumeCard =
    authoring && authoring.revision !== null && authoring.status !== "not_started" ? (
      <div style={{ padding: "0 24px 16px 24px" }}>
        <ResumeCard
          featureName={featureName}
          title={authoring.featureTitle ?? featureName}
          status={authoring.status}
          confirmed={authoring.progress.confirmed}
          total={authoring.progress.total}
          href={`/define/${featureName}/authoring/prd`}
        />
      </div>
    ) : null;

  const handleDismissBluf = useCallback(() => {
    setBlufDismissed(true);
    if (typeof window !== "undefined") {
      localStorage.setItem(`bluf-dismissed-${featureName}`, "true");
    }
  }, [featureName]);

  // Track previous state for scope diffing
  const prevStateRef = useRef<{ files: Set<string>; defects: number; learnings: number } | null>(null);

  const handleRefine = useCallback(
    async (newText: string) => {
      // Capture pre-refinement state
      const currentPkg = pkgData?.contextPackage;
      prevStateRef.current = {
        files: new Set(currentPkg?.codebase.map((c: any) => c.path) ?? []),
        defects: currentPkg?.defects.length ?? 0,
        learnings: currentPkg?.learnings.length ?? 0,
      };

      setRefining(true);
      setScopeDiff(null);
      try {
        await executeRefine({ featureName, text: newText });
        reexecutePkg({ requestPolicy: "network-only" });
      } finally {
        setRefining(false);
      }
    },
    [featureName, executeRefine, reexecutePkg, pkgData]
  );

  // Compute scope diff when data changes after refinement
  const pkgRef = pkgData?.contextPackage;
  const pkgAssembledAt = pkgRef?.assembledAt;
  React.useEffect(() => {
    if (!prevStateRef.current || !pkgRef || refining) return;
    const prev = prevStateRef.current;
    prevStateRef.current = null;
    const newFiles = new Set(pkgRef.codebase.map((c: any) => c.path));
    const added = [...newFiles].filter((f: string) => !prev.files.has(f)).length;
    const removed = [...prev.files].filter((f) => !newFiles.has(f)).length;
    const defectsDelta = pkgRef.defects.length - prev.defects;
    const learningsDelta = pkgRef.learnings.length - prev.learnings;
    if (added > 0 || removed > 0 || defectsDelta !== 0 || learningsDelta !== 0) {
      setScopeDiff({ filesAdded: added, filesRemoved: removed, defectsDelta, learningsDelta });
      setTimeout(() => setScopeDiff(null), 5000);
    }
  }, [pkgAssembledAt, refining]); // eslint-disable-line react-hooks/exhaustive-deps

  // Invalid feature name
  if (!isValidFeatureName(featureName)) {
    return (
      <div style={{ display: "flex", height: "100vh" }}>
        <IconRail />
        <div
          style={{
            flex: 1,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <span
            className="type-body"
            style={{ color: "var(--color-text-tertiary)" }}
          >
            Feature name is invalid
          </span>
        </div>
      </div>
    );
  }

  // Loading
  if (pkgFetching && !pkgData) {
    return (
      <div style={{ display: "flex", height: "100vh" }}>
        <IconRail />
        <div
          style={{
            flex: 1,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <span
            className="type-body"
            style={{ color: "var(--color-text-tertiary)" }}
          >
            Loading context...
          </span>
        </div>
      </div>
    );
  }

  // No context package (feature doesn't exist or hasn't been declared)
  if (!pkgData?.contextPackage) {
    return (
      <div style={{ display: "flex", height: "100vh" }}>
        <IconRail />
        <div
          style={{
            flex: 1,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <span
            className="type-body"
            style={{ color: "var(--color-text-tertiary)" }}
          >
            {pkgError
              ? `Error loading context: ${pkgError.message}`
              : "No context package found for this feature."}
          </span>
        </div>
      </div>
    );
  }

  const pkg = pkgData.contextPackage;

  // BLUF view (first visit)
  if (!blufDismissed) {
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
              overflowY: "auto",
              padding: "48px 48px 80px",
            }}
          >
            <ErrorBoundary>
              <BlufView
                featureName={featureName}
                contextPackage={pkg}
                assembledAt={pkg.assembledAt}
                onDismiss={handleDismissBluf}
              />
            </ErrorBoundary>
          </main>
        </div>
      </div>
    );
  }

  // Editor layout with context panel + editor + validation gutter
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
        {resumeCard && <div style={{ paddingTop: 16 }}>{resumeCard}</div>}
        <div style={{ flex: 1, display: "flex", overflow: "hidden", position: "relative" }}>
          <ErrorBoundary>
            <CeremonyLayout
              featureName={featureName}
              contextPackage={pkg}
              onRefine={handleRefine}
              refining={refining}
            />
          </ErrorBoundary>
          {/* Scope diff toast */}
          {scopeDiff && (
            <div style={{
              position: "absolute",
              bottom: 24,
              left: "50%",
              transform: "translateX(-50%)",
              background: "var(--color-bg-elevated)",
              border: "1px solid var(--color-border)",
              borderRadius: 8,
              padding: "10px 20px",
              fontSize: 12,
              color: "var(--color-text-secondary)",
              display: "flex",
              gap: 16,
              zIndex: 10,
              boxShadow: "0 4px 12px rgba(0,0,0,0.3)",
            }}>
              {scopeDiff.filesAdded > 0 && (
                <span style={{ color: "var(--color-accent)" }}>+{scopeDiff.filesAdded} files</span>
              )}
              {scopeDiff.filesRemoved > 0 && (
                <span style={{ color: "var(--color-red)" }}>-{scopeDiff.filesRemoved} files</span>
              )}
              {scopeDiff.defectsDelta !== 0 && (
                <span style={{ color: scopeDiff.defectsDelta > 0 ? "var(--color-amber)" : "var(--color-accent)" }}>
                  {scopeDiff.defectsDelta > 0 ? "+" : ""}{scopeDiff.defectsDelta} defects
                </span>
              )}
              {scopeDiff.learningsDelta !== 0 && (
                <span>
                  {scopeDiff.learningsDelta > 0 ? "+" : ""}{scopeDiff.learningsDelta} learnings
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
