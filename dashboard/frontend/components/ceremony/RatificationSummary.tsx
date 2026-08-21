"use client";

import React from "react";
import type { CommitRecord, RatificationState, VerdictEntry } from "@/lib/graphql/queries/ceremony-commitment";

interface RatificationSummaryProps {
  commitRecord: CommitRecord;
  ratificationState: RatificationState;
}

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function RatificationSummary({ commitRecord, ratificationState }: RatificationSummaryProps) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Approval counter */}
      <div>
        <div style={{ display: "flex", alignItems: "baseline", gap: 4, marginBottom: 4 }}>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 28, fontWeight: 600, color: "var(--color-text)", lineHeight: 1.1 }}>
            {ratificationState.ratificationCount}
          </span>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 15, fontWeight: 400, color: "var(--color-text-tertiary)" }}>
            /{ratificationState.threshold}
          </span>
        </div>
        <div style={{ fontFamily: "var(--font-sans)", fontSize: 11, fontWeight: 500, color: "var(--color-text-secondary)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
          Approvals needed
        </div>
      </div>

      {/* Suggestion summary */}
      <div>
        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--color-text)", marginBottom: 8 }}>
          Suggestions
        </div>
        <div style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.5 }}>
          <span style={{ fontFamily: "var(--font-mono)", fontWeight: 500, color: "var(--color-text)" }}>
            {commitRecord.suggestionHistory.received}
          </span> received,{" "}
          <span style={{ fontFamily: "var(--font-mono)", fontWeight: 500, color: "var(--color-emerald)" }}>
            {commitRecord.suggestionHistory.accepted}
          </span> accepted,{" "}
          <span style={{ fontFamily: "var(--font-mono)", fontWeight: 500, color: "var(--color-text-tertiary)" }}>
            {commitRecord.suggestionHistory.dismissed.count}
          </span> dismissed
        </div>
        {commitRecord.suggestionHistory.dismissed.reasons.length > 0 && (
          <div style={{ marginTop: 6, fontSize: 12, color: "var(--color-text-tertiary)" }}>
            {commitRecord.suggestionHistory.dismissed.reasons.map((r, i) => (
              <div key={i}>Dismissed: "{r}"</div>
            ))}
          </div>
        )}
      </div>

      {/* Commit metadata */}
      <div>
        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--color-text)", marginBottom: 8 }}>
          Commit
        </div>
        <div style={{ fontSize: 12, color: "var(--color-text-secondary)", display: "flex", flexDirection: "column", gap: 4 }}>
          <div>By {commitRecord.claimant}</div>
          <div>{relativeTime(commitRecord.committedAt)}</div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--color-text-tertiary)" }}>
            {commitRecord.validationStateRef}
          </div>
        </div>
      </div>

      {/* Verdicts */}
      <div>
        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--color-text)", marginBottom: 8 }}>
          Verdicts
        </div>
        {ratificationState.verdicts.length === 0 ? (
          <div style={{ fontSize: 13, color: "var(--color-text-tertiary)" }}>No votes yet</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {ratificationState.verdicts.map((v) => (
              <div key={v.id} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "var(--color-text-secondary)" }}>
                <span
                  style={{
                    width: 8, height: 8, borderRadius: "50%", flexShrink: 0,
                    background: v.verdict === "approve" ? "var(--color-emerald)" : "var(--color-red)",
                  }}
                />
                <span>{v.actor}</span>
                <span style={{ color: "var(--color-text-tertiary)" }}>
                  {v.verdict === "approve" ? "Approved" : "Rejected"}
                </span>
                <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--color-text-tertiary)" }}>
                  {relativeTime(v.timestamp)}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
