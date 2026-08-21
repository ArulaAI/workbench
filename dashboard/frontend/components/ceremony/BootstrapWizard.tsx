"use client";

import React, { useState } from "react";
import { Check, Loader2 } from "lucide-react";
import { useMutation, useQuery } from "urql";
import {
  BOOTSTRAP_STATUS_QUERY,
  START_GRAPH_BUILD_MUTATION,
  GENERATE_VISION_MUTATION,
  COMMIT_VISION_MUTATION,
  EXTRACT_CONVENTIONS_MUTATION,
  RESOLVE_CONVENTION_MUTATION,
  COMMIT_CONVENTIONS_MUTATION,
  COMPLETE_BOOTSTRAP_MUTATION,
} from "@/lib/graphql/queries/ceremony-bootstrap";
import type {
  BootstrapStatus,
  Convention,
  BootstrapStatusData,
} from "@/lib/graphql/queries/ceremony-bootstrap";
import { VisionDraftEditor } from "./VisionDraftEditor";
import { ConventionReview } from "./ConventionReview";

interface BootstrapWizardProps {
  onComplete: () => void;
}

const STEPS = ["Graph", "Vision", "Conventions", "Complete"] as const;

function StepIndicator({ current, completed }: { current: number; completed: number[] }) {
  return (
    <div style={{ display: "flex", gap: 0, alignItems: "center", marginBottom: 24 }}>
      {STEPS.map((label, i) => {
        const isComplete = completed.includes(i);
        const isCurrent = i === current;
        const isFuture = !isComplete && !isCurrent;
        return (
          <React.Fragment key={label}>
            {i > 0 && (
              <div
                style={{
                  flex: 1,
                  height: 1,
                  background: isComplete || isCurrent
                    ? "var(--color-accent)"
                    : "var(--color-border)",
                  transition: "background 300ms",
                }}
              />
            )}
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <div
                style={{
                  width: 24, height: 24, borderRadius: "50%",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: 11, fontWeight: 600, fontFamily: "var(--font-mono)",
                  background: isComplete ? "var(--color-accent)" : "transparent",
                  color: isComplete ? "var(--color-bg)" : isCurrent ? "var(--color-text)" : "var(--color-text-tertiary)",
                  border: isComplete ? "none" : `1px solid ${isCurrent ? "var(--color-text)" : "var(--color-text-tertiary)"}`,
                  transition: "all 300ms",
                }}
              >
                {isComplete ? <Check size={12} /> : i + 1}
              </div>
              <span
                style={{
                  fontSize: 11, fontWeight: 500,
                  color: isComplete ? "var(--color-accent)" : isCurrent ? "var(--color-text)" : "var(--color-text-tertiary)",
                }}
              >
                {label}
              </span>
            </div>
          </React.Fragment>
        );
      })}
    </div>
  );
}

export function BootstrapWizard({ onComplete }: BootstrapWizardProps) {
  const [step, setStep] = useState(0);
  const [completedSteps, setCompletedSteps] = useState<number[]>([]);
  const [graphResult, setGraphResult] = useState<{ fileCount: number; nodeCount: number } | null>(null);
  const [visionContent, setVisionContent] = useState("");
  const [conventions, setConventions] = useState<Convention[]>([]);
  const [building, setBuilding] = useState(false);

  const [, startBuild] = useMutation(START_GRAPH_BUILD_MUTATION);
  const [, generateVision] = useMutation(GENERATE_VISION_MUTATION);
  const [, commitVision] = useMutation(COMMIT_VISION_MUTATION);
  const [, extractConventions] = useMutation(EXTRACT_CONVENTIONS_MUTATION);
  const [, resolveConvention] = useMutation(RESOLVE_CONVENTION_MUTATION);
  const [, commitConventions] = useMutation(COMMIT_CONVENTIONS_MUTATION);
  const [, completeBootstrap] = useMutation(COMPLETE_BOOTSTRAP_MUTATION);

  const advanceStep = (from: number) => {
    setCompletedSteps((prev) => [...new Set([...prev, from])]);
    setStep(from + 1);
  };

  const handleStartBuild = async () => {
    setBuilding(true);
    const result = await startBuild({});
    if (result.data?.startGraphBuild) {
      setGraphResult({
        fileCount: result.data.startGraphBuild.fileCount,
        nodeCount: result.data.startGraphBuild.nodeCount,
      });
    }
    setBuilding(false);
  };

  const handleGenerateVision = async () => {
    const result = await generateVision({});
    if (result.data?.generateVision) {
      setVisionContent(result.data.generateVision.generatedContent);
    }
  };

  const handleCommitVision = async (content: string) => {
    await commitVision({ content });
    advanceStep(1);
    const result = await extractConventions({});
    if (result.data?.extractConventions) {
      setConventions(result.data.extractConventions);
    }
  };

  const handleResolveConvention = async (id: string, action: "accept" | "reject") => {
    await resolveConvention({ conventionId: id, action });
    setConventions((prev) =>
      prev.map((c) => (c.id === id ? { ...c, status: action === "accept" ? "accepted" : "rejected" } : c))
    );
  };

  const handleCommitConventions = async (acceptedIds: string[], persona: string) => {
    await commitConventions({ personaInput: persona || undefined });
    advanceStep(2);
  };

  const handleComplete = async () => {
    await completeBootstrap({});
    onComplete();
  };

  return (
    <div style={{ display: "flex", justifyContent: "center", alignItems: "center", padding: 24, minHeight: "100%" }}>
      <div className="surface" style={{ width: "100%", maxWidth: 640, padding: 24 }}>
        <StepIndicator current={step} completed={completedSteps} />

        {/* Step 0: Graph Build */}
        {step === 0 && (
          <div>
            <h2 style={{ fontSize: 15, fontWeight: 600, color: "var(--color-text)", marginBottom: 4 }}>
              Build Semantic Graph
            </h2>
            <p style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.5, marginBottom: 16 }}>
              SPEED will analyze your codebase to build a semantic understanding of your project structure, dependencies, and patterns.
            </p>
            {graphResult ? (
              <div style={{ padding: 16, background: "var(--color-bg-elevated)", borderRadius: 8, marginBottom: 16 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                  <Check size={16} style={{ color: "var(--color-accent)" }} />
                  <span style={{ fontSize: 13, fontWeight: 500, color: "var(--color-accent)" }}>Graph built</span>
                </div>
                <div style={{ display: "flex", gap: 24 }}>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: 13, color: "var(--color-text-secondary)" }}>
                    {graphResult.fileCount} files
                  </span>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: 13, color: "var(--color-text-secondary)" }}>
                    {graphResult.nodeCount} nodes
                  </span>
                </div>
              </div>
            ) : building ? (
              <div style={{ display: "flex", alignItems: "center", gap: 8, padding: 16, marginBottom: 16 }}>
                <Loader2 size={16} style={{ color: "var(--color-accent)", animation: "spin 1s linear infinite" }} />
                <span style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>Analyzing codebase...</span>
              </div>
            ) : null}
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
              {!graphResult && !building && (
                <button onClick={handleStartBuild} style={{
                  fontSize: 13, fontWeight: 600, padding: "8px 20px", borderRadius: 8,
                  background: "var(--color-accent)", color: "var(--color-bg)", border: "none", cursor: "pointer",
                }}>
                  Start Build
                </button>
              )}
              {graphResult && (
                <button onClick={() => { advanceStep(0); handleGenerateVision(); }} style={{
                  fontSize: 13, fontWeight: 600, padding: "8px 20px", borderRadius: 8,
                  background: "var(--color-accent)", color: "var(--color-bg)", border: "none", cursor: "pointer",
                }}>
                  Continue
                </button>
              )}
            </div>
          </div>
        )}

        {/* Step 1: Vision */}
        {step === 1 && (
          <div>
            <h2 style={{ fontSize: 15, fontWeight: 600, color: "var(--color-text)", marginBottom: 4 }}>
              Product Vision
            </h2>
            <p style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.5, marginBottom: 16 }}>
              SPEED generated a draft vision from your codebase. Review the generated version and edit your own.
            </p>
            <VisionDraftEditor
              generatedContent={visionContent}
              onCommit={handleCommitVision}
              onSkip={() => advanceStep(1)}
              onRegenerate={handleGenerateVision}
            />
          </div>
        )}

        {/* Step 2: Conventions */}
        {step === 2 && (
          <div>
            <h2 style={{ fontSize: 15, fontWeight: 600, color: "var(--color-text)", marginBottom: 4 }}>
              Project Conventions
            </h2>
            <p style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.5, marginBottom: 16 }}>
              SPEED derived these conventions from your codebase and commit history. Accept the ones that reflect your team's standards.
            </p>
            <ConventionReview
              conventions={conventions}
              onResolve={handleResolveConvention}
              onCommit={handleCommitConventions}
              onSkip={() => advanceStep(2)}
            />
          </div>
        )}

        {/* Step 3: Complete */}
        {step === 3 && (
          <div style={{ textAlign: "center", padding: "32px 0" }}>
            <div
              style={{
                width: 48, height: 48, borderRadius: "50%",
                background: "var(--color-accent-dim)", color: "var(--color-accent)",
                display: "flex", alignItems: "center", justifyContent: "center",
                margin: "0 auto 16px",
              }}
            >
              <Check size={24} />
            </div>
            <h2 style={{ fontSize: 15, fontWeight: 600, color: "var(--color-text)", marginBottom: 16 }}>
              Setup Complete
            </h2>
            <div style={{ display: "flex", justifyContent: "center", gap: 24, marginBottom: 24 }}>
              {graphResult && (
                <span style={{ fontFamily: "var(--font-mono)", fontSize: 13, color: "var(--color-text-secondary)" }}>
                  {graphResult.fileCount} files indexed
                </span>
              )}
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 13, color: "var(--color-text-secondary)" }}>
                {conventions.filter((c) => c.status === "accepted").length} conventions accepted
              </span>
            </div>
            <p style={{ fontSize: 13, color: "var(--color-text-secondary)", marginBottom: 24 }}>
              You're ready to define your first feature.
            </p>
            <button onClick={handleComplete} style={{
              fontSize: 13, fontWeight: 600, padding: "10px 24px", borderRadius: 8,
              background: "var(--color-accent)", color: "var(--color-bg)", border: "none", cursor: "pointer",
            }}>
              Start Defining
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
