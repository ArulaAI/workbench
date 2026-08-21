"use client";

import React from "react";
import type { SpecClaimInfo } from "@/lib/graphql/queries/ceremony";

interface ClaimHistoryPanelProps {
  claims: SpecClaimInfo[];
}

function formatRelativeTime(isoDate: string): string {
  const diff = Date.now() - Date.parse(isoDate);
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

type EventKind = "claimed" | "released" | "stale-takeover" | "committed";

interface TimelineEntry {
  specType: string;
  claimant: string;
  kind: EventKind;
  at: string;
}

function specLabel(specType: string): string {
  if (specType === "prd") return "PRD";
  if (specType === "design") return "Design";
  if (specType === "rfc") return "RFC";
  if (specType.startsWith("rfc-")) return `RFC: ${specType.slice(4)}`;
  return specType.toUpperCase();
}

function deriveTimeline(claims: SpecClaimInfo[]): TimelineEntry[] {
  const entries: TimelineEntry[] = [];

  for (const claim of claims) {
    entries.push({
      specType: claim.specType,
      claimant: claim.claimant,
      kind: "claimed",
      at: claim.claimedAt,
    });

    if (claim.releasedAt) {
      entries.push({
        specType: claim.specType,
        claimant: claim.claimant,
        kind: "released",
        at: claim.releasedAt,
      });
    }
  }

  entries.sort((a, b) => Date.parse(b.at) - Date.parse(a.at));
  return entries;
}

const kindColors: Record<EventKind, string> = {
  claimed: "var(--color-accent)",
  released: "var(--color-text-tertiary)",
  "stale-takeover": "var(--color-amber)",
  committed: "var(--color-emerald)",
};

/**
 * Renders claim activity as a compact timeline. Designed to be used
 * inside a ContextPanel <Section> — it only renders the body content,
 * not its own collapsible header.
 */
export function ClaimHistoryPanel({ claims }: ClaimHistoryPanelProps) {
  const timeline = deriveTimeline(claims);
  if (timeline.length === 0) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
      {timeline.map((entry, i) => (
        <div
          key={`${entry.specType}-${entry.kind}-${entry.at}-${i}`}
          style={{
            display: "flex",
            alignItems: "baseline",
            gap: 6,
            padding: "5px 0",
            borderBottom:
              i < timeline.length - 1
                ? "1px solid var(--color-border-light)"
                : "none",
            fontSize: 12,
          }}
        >
          {/* Dot */}
          <div
            style={{
              width: 5,
              height: 5,
              borderRadius: "50%",
              background: kindColors[entry.kind],
              flexShrink: 0,
              position: "relative",
              top: -1,
            }}
          />

          {/* Name */}
          <span style={{ color: "var(--color-text-secondary)" }}>
            {entry.claimant}
          </span>

          {/* Action */}
          <span style={{ color: kindColors[entry.kind], fontWeight: 500 }}>
            {entry.kind === "stale-takeover" ? "took over" : entry.kind}
          </span>

          {/* Spec type */}
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              fontWeight: 500,
              color: "var(--color-text-secondary)",
            }}
          >
            {specLabel(entry.specType)}
          </span>

          {/* Time — pushed right */}
          <span
            style={{
              marginLeft: "auto",
              fontSize: 10,
              color: "var(--color-text-tertiary)",
              flexShrink: 0,
            }}
          >
            {formatRelativeTime(entry.at)}
          </span>
        </div>
      ))}
    </div>
  );
}
