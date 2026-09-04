"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { ErrorBoundary } from "@/components/shared/error-boundary";
import { DigestHeader } from "@/components/digest/DigestHeader";
import { FootprintGrid } from "@/components/digest/FootprintGrid";
import { DomainList } from "@/components/digest/DomainList";
import { DigestStateGate } from "@/components/digest/DigestStateGate";
import { useRepositoryDigest } from "@/lib/hooks/useRepositoryDigest";
import type { RepositoryDigestData } from "@/lib/graphql/queries/repository-digest";

// A feature name follows the same rule Define's own route uses.
const FEATURE_RE = /^[a-z0-9][a-z0-9-]*$/;

function isValidFeatureName(name: string | null): name is string {
  return !!name && name.length <= 50 && FEATURE_RE.test(name);
}

// useSearchParams() requires a Suspense boundary somewhere above it in a
// Client Component (Next.js App Router: without one, `next build` bails
// the route out of static rendering with "missing-suspense-with-csr-
// bailout" and can fail the build outright) — this is the only route in
// the app using the hook, so there's no existing boundary to reuse. The
// exported page stays a thin wrapper; all the real content (which reads
// searchParams to build returnToDefineHref) moves into the child so
// Suspense has something to actually suspend.
export default function DigestOverviewPage() {
  return (
    <Suspense fallback={null}>
      <DigestOverviewContent />
    </Suspense>
  );
}

function DigestOverviewContent() {
  const searchParams = useSearchParams();
  const returnTo = searchParams.get("returnTo");
  const featureParam = searchParams.get("feature");
  const returnToDefineHref =
    returnTo === "define" && isValidFeatureName(featureParam)
      ? `/define/${encodeURIComponent(featureParam)}`
      : null;

  const { digest, fetching, error, status, refreshing, refreshError, dismissRefreshError, handleRefresh } =
    useRepositoryDigest();

  return (
    <ErrorBoundary>
      <DigestStateGate
        fetching={fetching}
        error={error}
        digest={digest}
        status={status}
        refreshing={refreshing}
        refreshError={refreshError}
        onDismissRefreshError={dismissRefreshError}
        onRefresh={handleRefresh}
      >
        {(d) => (
          <>
            <DigestHeader
              digest={d}
              onRefresh={() => handleRefresh(false)}
              refreshing={refreshing}
              returnToDefineHref={returnToDefineHref}
            />
            <FootprintGrid footprint={d.footprint} />
            <LanguageComposition footprint={d.footprint} />
            <DomainList domains={d.domains} />
          </>
        )}
      </DigestStateGate>
    </ErrorBoundary>
  );
}

/**
 * The manager reference's "4-layer architecture flow" (React client → REST
 * API → services → persistence) names specific architectural roles this
 * backend has no way to verify for an arbitrary repository — that
 * classification is real future work (see Architecture, "Soon"), not
 * something to fake here. What footprint.languages *does* give us
 * honestly is the repository's actual language composition, already
 * computed by the builder — a real, deterministic, presentation-only
 * summary of "what this repository is actually made of," not an
 * invented flow diagram.
 */
function LanguageComposition({ footprint }: { footprint: RepositoryDigestData["footprint"] }) {
  const languages = [...footprint.languages].sort((a, b) => b.percent - a.percent);
  if (languages.length === 0) return null;

  const swatchColors = [
    "var(--color-accent)",
    "var(--color-violet)",
    "var(--color-blue)",
    "var(--color-cyan)",
    "var(--color-amber)",
    "var(--color-text-tertiary)",
  ];

  return (
    <div className="surface" style={{ padding: 20 }}>
      <div className="digest-section-title" style={{ marginBottom: 4 }}>
        Language composition
      </div>
      <p className="type-caption" style={{ marginBottom: 12 }}>
        Share of indexed lines by language, from the project map.
      </p>
      <div
        className="progress-track"
        style={{ height: 8, marginBottom: 12 }}
        role="img"
        aria-label={languages.map((l) => `${l.name} ${l.percent.toFixed(0)}%`).join(", ")}
      >
        {languages.map((l, i) => (
          <div
            key={l.name}
            style={{
              width: `${l.percent}%`,
              background: swatchColors[i % swatchColors.length],
              minWidth: l.percent > 0 ? 2 : 0,
            }}
          />
        ))}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "8px 18px" }}>
        {languages.map((l, i) => (
          <div key={l.name} style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span
              style={{
                width: 8, height: 8, borderRadius: 2, flexShrink: 0,
                background: swatchColors[i % swatchColors.length],
              }}
            />
            <span className="type-caption" style={{ color: "var(--color-text-secondary)" }}>
              {l.name} · {l.percent.toFixed(0)}% · {l.files.toLocaleString()} files
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
