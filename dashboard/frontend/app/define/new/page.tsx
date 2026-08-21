"use client";

import { useQuery } from "urql";
import { ErrorBoundary } from "@/components/shared/error-boundary";
import { IconRail } from "@/components/landing/IconRail";
import { Header } from "@/components/layout/header";
import { IntentInput } from "@/components/ceremony/IntentInput";
import { BootstrapWizard } from "@/components/ceremony/BootstrapWizard";
import {
  BOOTSTRAP_STATUS_QUERY,
  type BootstrapStatusData,
} from "@/lib/graphql/queries/ceremony-bootstrap";

/**
 * Route: /define/new
 * Checks bootstrap status first. If bootstrap needed, renders the wizard.
 * Otherwise renders IntentInput for declaring a new ceremony.
 */
export default function DefineNewPage() {
  const [{ data, fetching }] = useQuery<BootstrapStatusData>({
    query: BOOTSTRAP_STATUS_QUERY,
  });

  const needsBootstrap = data?.bootstrapStatus?.needsBootstrap ?? false;

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
            justifyContent: "center",
            alignItems: "center",
            padding: 24,
          }}
        >
          <ErrorBoundary>
            {fetching ? null : needsBootstrap ? (
              <BootstrapWizard onComplete={() => window.location.reload()} />
            ) : (
              <IntentInput />
            )}
          </ErrorBoundary>
        </main>
      </div>
    </div>
  );
}
