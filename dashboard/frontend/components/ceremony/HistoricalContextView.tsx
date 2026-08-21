"use client";

import Link from "next/link";
import type { ContextPackage } from "@/lib/graphql/queries/ceremony";
import { ContextSnapshot } from "./ContextSnapshot";
import { ContextDiff } from "./ContextDiff";

/* ── Props ─────────────────────────────────────────────────── */

interface HistoricalContextViewProps {
  featureName: string;
  snapshot: ContextPackage;
  current: ContextPackage | null;
  currentAssemblyStatus: string;
  currentAssemblyError: string | null;
  author: string;
  committedAt: string;
}

/* ── Main component ────────────────────────────────────────── */

export function HistoricalContextView({
  featureName,
  snapshot,
  current,
  currentAssemblyStatus,
  currentAssemblyError,
  author,
  committedAt,
}: HistoricalContextViewProps) {
  const formattedDate = new Date(committedAt).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        overflow: "hidden",
      }}
    >
      {/* Header bar */}
      <div
        style={{
          height: 52,
          flexShrink: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "0 20px",
          background: "var(--color-bg-elevated)",
          borderBottom: "1px solid var(--color-border)",
        }}
      >
        {/* Left: feature name + metadata */}
        <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
          <span
            style={{
              fontFamily: "var(--font-sans)",
              fontSize: 15,
              fontWeight: 600,
              color: "var(--color-text)",
            }}
          >
            {featureName}
          </span>
          <span
            style={{
              fontFamily: "var(--font-sans)",
              fontSize: 11,
              fontWeight: 400,
              color: "var(--color-text-tertiary)",
            }}
          >
            {author} &middot; {formattedDate}
          </span>
        </div>

        {/* Right: back link */}
        <Link
          href={`/define/${featureName}`}
          style={{
            fontFamily: "var(--font-sans)",
            fontSize: 11,
            fontWeight: 400,
            color: "var(--color-text-tertiary)",
            textDecoration: "none",
            transition: "color 0.15s",
          }}
          onMouseEnter={(e) => {
            (e.target as HTMLElement).style.color =
              "var(--color-text-secondary)";
          }}
          onMouseLeave={(e) => {
            (e.target as HTMLElement).style.color =
              "var(--color-text-tertiary)";
          }}
        >
          &larr; Back to ceremony
        </Link>
      </div>

      {/* Two-column body */}
      <div
        style={{
          flex: 1,
          display: "flex",
          overflow: "hidden",
        }}
      >
        {/* Left: snapshot */}
        <div
          style={{
            flex: 1,
            minWidth: 0,
            background: "var(--color-bg-elevated)",
            overflowY: "auto",
          }}
        >
          <ContextSnapshot
            contextPackage={snapshot}
            assembledAt={snapshot.assembledAt}
          />
        </div>

        {/* Divider */}
        <div
          style={{
            width: 1,
            flexShrink: 0,
            background: "var(--color-border)",
          }}
        />

        {/* Right: diff or error */}
        <div
          style={{
            flex: 1,
            minWidth: 0,
            background: "var(--color-bg-card)",
            overflowY: "auto",
          }}
        >
          {current ? (
            <ContextDiff snapshot={snapshot} current={current} />
          ) : currentAssemblyStatus === "error" ? (
            <div
              style={{
                height: "100%",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                padding: 24,
              }}
            >
              <div
                style={{
                  textAlign: "center",
                  maxWidth: 320,
                }}
              >
                <div
                  style={{
                    fontFamily: "var(--font-sans)",
                    fontSize: 13,
                    fontWeight: 500,
                    color: "var(--color-red)",
                    marginBottom: 8,
                  }}
                >
                  Context assembly failed
                </div>
                {currentAssemblyError && (
                  <div
                    style={{
                      fontFamily: "var(--font-sans)",
                      fontSize: 12,
                      fontWeight: 400,
                      color: "var(--color-text-tertiary)",
                      lineHeight: 1.5,
                    }}
                  >
                    {currentAssemblyError}
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div
              style={{
                height: "100%",
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
                }}
              >
                No current context available for comparison.
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
