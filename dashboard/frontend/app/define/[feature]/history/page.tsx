"use client";

import { useParams } from "next/navigation";
import { useQuery } from "urql";
import { IconRail } from "@/components/landing/IconRail";
import { Header } from "@/components/layout/header";
import { HistoricalContextView } from "@/components/ceremony/HistoricalContextView";
import {
  CONTEXT_HISTORY_QUERY,
  type ContextHistoryData,
  type ContextHistoryVars,
} from "@/lib/graphql/queries/ceremony-context";

const FEATURE_RE = /^[a-z0-9][a-z0-9-]*$/;

function isValidFeatureName(name: string): boolean {
  return name.length > 0 && name.length <= 50 && FEATURE_RE.test(name);
}

export default function DefineFeatureHistoryPage() {
  const params = useParams<{ feature: string }>();
  const featureName = params.feature;

  const [{ data, fetching, error }] = useQuery<
    ContextHistoryData,
    ContextHistoryVars
  >({
    query: CONTEXT_HISTORY_QUERY,
    variables: { featureName },
    pause: !isValidFeatureName(featureName),
  });

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
  if (fetching && !data) {
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
            Loading context history...
          </span>
        </div>
      </div>
    );
  }

  // Error
  if (error) {
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
            Error loading history: {error.message}
          </span>
        </div>
      </div>
    );
  }

  const history = data?.contextHistory;

  // No snapshot available
  if (!history?.snapshot) {
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
          <div
            style={{
              flex: 1,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              padding: 24,
            }}
          >
            <span
              style={{
                fontFamily: "var(--font-sans)",
                fontSize: 13,
                fontWeight: 400,
                color: "var(--color-text-tertiary)",
                maxWidth: 400,
                textAlign: "center",
                lineHeight: 1.5,
              }}
            >
              No context snapshot available for this feature. Context persistence
              was not active when this spec was authored.
            </span>
          </div>
        </div>
      </div>
    );
  }

  const ceremony = history.ceremony;
  const author = ceremony?.author ?? "unknown";
  const committedAt =
    ceremony?.currentRevision?.createdAt ?? history.snapshot.assembledAt;

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
        <div style={{ flex: 1, overflow: "hidden" }}>
          <HistoricalContextView
            featureName={featureName}
            snapshot={history.snapshot}
            current={history.current}
            currentAssemblyStatus={history.currentAssemblyStatus}
            currentAssemblyError={history.currentAssemblyError}
            author={author}
            committedAt={committedAt}
          />
        </div>
      </div>
    </div>
  );
}
