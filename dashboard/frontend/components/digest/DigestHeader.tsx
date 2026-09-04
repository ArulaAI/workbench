"use client";

import type { RepositoryDigestData } from "@/lib/graphql/queries/repository-digest";

export function DigestHeader({
  digest,
  onRefresh,
  refreshing,
  returnToDefineHref,
}: {
  digest: RepositoryDigestData;
  onRefresh: () => void;
  refreshing: boolean;
  returnToDefineHref: string | null;
}) {
  // "—" for a repository with no git history — an empty string here
  // rendered a visibly broken "CURRENT ·  · <date>" doubled middot,
  // unlike quality/page.tsx's FreshnessStrip, which already falls back
  // to "—" for the same nullable field.
  const shortHead = digest.freshness.currentGitHead?.slice(0, 7) ?? "—";
  const stateColor =
    digest.effectiveState === "CURRENT"
      ? "var(--color-emerald)"
      : digest.effectiveState === "STALE"
      ? "var(--color-amber)"
      : "var(--color-text-tertiary)";

  return (
    <div className="surface" style={{ padding: 20, display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16 }}>
        <div>
          <div className="digest-eyebrow" style={{ display: "flex", alignItems: "center", gap: 10 }}>
            Repository Digest
            <span className="type-caption" style={{ color: stateColor }}>
              {digest.effectiveState} · {shortHead} ·{" "}
              {new Date(digest.generatedAt).toLocaleString()}
            </span>
          </div>
          <div className="digest-title" style={{ marginTop: 4 }}>
            {digest.identity.name}
          </div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          {returnToDefineHref && (
            <a
              href={returnToDefineHref}
              className="type-badge"
              style={{
                padding: "8px 12px",
                borderRadius: 8,
                border: "1px solid var(--color-border)",
                color: "var(--color-text-secondary)",
                textDecoration: "none",
              }}
            >
              ← Return to Define
            </a>
          )}
          <button
            type="button"
            onClick={onRefresh}
            disabled={refreshing}
            className="type-badge"
            style={{
              padding: "8px 14px",
              borderRadius: 8,
              border: "1px solid var(--color-accent)",
              background: refreshing ? "transparent" : "var(--color-accent-dim)",
              color: "var(--color-accent)",
              cursor: refreshing ? "default" : "pointer",
            }}
          >
            {refreshing ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </div>
      {digest.identity.summary && <p className="type-body">{digest.identity.summary}</p>}
    </div>
  );
}
