"use client";

import { useEffect, useCallback } from "react";
import { useQuery, useMutation, useSubscription } from "urql";
import {
  LANDING_VIEW_QUERY,
  RESPOND_TO_ESCALATION_MUTATION,
  TASK_STATUS_SUBSCRIPTION,
} from "@/lib/graphql/queries/landing";
import {
  PROCESS_STATUS_QUERY,
  PROCESS_STATUS_SUBSCRIPTION,
  type ProcessStatusData,
} from "@/lib/graphql/queries/process-status";
import type {
  LandingViewData,
  EscalationResponseData,
} from "@/lib/graphql/queries/landing";
import { IconRail } from "@/components/landing/IconRail";
import { TopBar } from "@/components/landing/TopBar";
import { EditorialGrid } from "@/components/landing/EditorialGrid";
import { DefinePanel } from "@/components/landing/DefinePanel";
import { JudgePanel } from "@/components/landing/JudgePanel";
import { ExecutePanel } from "@/components/landing/ExecutePanel";
import { LearnPanel } from "@/components/landing/LearnPanel";
import { StatusBar } from "@/components/landing/StatusBar";
import { Skeleton } from "@/components/shared/loading-skeleton";

function SkeletonPanel() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <Skeleton className="h-3 w-16" />
      <Skeleton className="h-5 w-24" />
      <Skeleton className="mt-2 h-3 w-full" />
      <Skeleton className="h-3 w-3/4" />
      <Skeleton className="h-3 w-1/2" />
    </div>
  );
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div
      role="alert"
      style={{
        margin: "16px 32px",
        borderRadius: 8,
        padding: 12,
        border: "1px solid var(--color-red)",
        backgroundColor: "rgba(239, 68, 100, 0.08)",
        color: "var(--color-red)",
        fontSize: 13,
      }}
    >
      {message}
    </div>
  );
}

export default function Home() {
  const [{ data, fetching, error }, reexecQuery] =
    useQuery<LandingViewData>({ query: LANDING_VIEW_QUERY });

  const [{ data: processData }, refetchProcess] =
    useQuery<ProcessStatusData>({ query: PROCESS_STATUS_QUERY });

  useSubscription(
    { query: PROCESS_STATUS_SUBSCRIPTION, variables: {} },
    useCallback(() => {
      refetchProcess({ requestPolicy: "network-only" });
    }, [refetchProcess]),
  );

  const [, executeMutation] = useMutation<EscalationResponseData>(
    RESPOND_TO_ESCALATION_MUTATION
  );

  const activeFeature =
    data?.landingView?.execute?.runningFeatures?.[0]?.name;

  const [{ data: subData, error: subError }] = useSubscription({
    query: TASK_STATUS_SUBSCRIPTION,
    variables: { feature: activeFeature ?? "" },
    pause: !activeFeature,
  });

  useEffect(() => {
    if (!subData?.taskStatusChanged) return;
    reexecQuery({ requestPolicy: "network-only" });
  }, [subData, reexecQuery]);

  async function handleEscalation(
    feature: string,
    taskId: string,
    response: string
  ) {
    const result = await executeMutation({ feature, taskId, response });
    if (result.data?.respondToEscalation?.success) {
      reexecQuery({ requestPolicy: "network-only" });
    }
  }

  const connected = activeFeature ? !subError : true;

  // Count unique features
  const featureNames = new Set<string>();
  if (data?.landingView) {
    const lv = data.landingView;
    lv.define.draftSpecs.forEach((s) => featureNames.add(s.name));
    lv.execute.runningFeatures.forEach((f) => featureNames.add(f.name));
    lv.learn.coverageTrend.forEach((t) => featureNames.add(t.feature));
    lv.learn.escalationTrend.forEach((t) => featureNames.add(t.feature));
  }

  const shell = (content: React.ReactNode) => (
    <div data-testid="landing-page" style={{ display: "flex", height: "100vh" }}>
      <IconRail />
      <div style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
        {content}
      </div>
    </div>
  );

  if (fetching) {
    return shell(
      <>
        <TopBar projectName="" branch="" />
        <EditorialGrid
          definePanel={<SkeletonPanel />}
          judgePanel={<SkeletonPanel />}
          executePanel={<SkeletonPanel />}
          learnPanel={<SkeletonPanel />}
        />
        <StatusBar projectName="" featureCount={0} runningCount={0} connected={false} />
      </>
    );
  }

  if (error || !data?.landingView) {
    return shell(
      <>
        <ErrorBanner message={error?.message ?? "Failed to load landing data"} />
        <StatusBar projectName="" featureCount={0} runningCount={0} connected={false} />
      </>
    );
  }

  const { landingView } = data;

  return shell(
    <>
      <TopBar
        projectName={landingView.projectName}
        branch={landingView.branch ?? ""}
      />
      <EditorialGrid
        definePanel={<DefinePanel define={landingView.define} />}
        judgePanel={
          <JudgePanel
            judge={landingView.judge}
            narrative={landingView.narrative}
          />
        }
        executePanel={
          <ExecutePanel
            execute={landingView.execute}
            onRespondToEscalation={handleEscalation}
          />
        }
        learnPanel={<LearnPanel {...landingView.learn} />}
      />
      <StatusBar
        projectName={landingView.projectName}
        featureCount={featureNames.size}
        runningCount={landingView.execute.runningFeatures.length}
        agentCount={processData?.processStatus?.features?.reduce(
          (sum, f) => sum + f.agents.length + f.supportAgents.length, 0
        ) ?? 0}
        staleCount={processData?.processStatus?.features?.reduce(
          (sum, f) => sum + f.staleProcesses.length, 0
        ) ?? 0}
        connected={connected}
      />
    </>
  );
}
