"use client";

import React from "react";
import { Check, AlertCircle, Lock, MessageCircle } from "lucide-react";
import type { ValidationState } from "@/lib/graphql/queries/ceremony";
import type { ClaimState } from "./ownership";
import { RatifyControl } from "./ownership";

/**
 * Ratification context passed into CommitBar when the viewer is a
 * non-committer of a committed spec. Drives the RatifyControl render.
 * When undefined, no ratify mode is possible and the bar shows the
 * normal Commit button (or its disabled variant).
 */
export interface RatifyContext {
  approvalCount: number;
  approvalThreshold: number;
  hasVoted: boolean;
  viewerIsCommitter: boolean;
  viewerVerdict?: "approve" | "reject" | null;
  busy: boolean;
  onApprove: (comment?: string) => void;
  onReject: (comment: string) => void;
}

interface CommitBarProps {
  activeSpecType: string;
  claimState: ClaimState;
  validationState: ValidationState | null;
  unresolvedSuggestionCount: number;
  resolvedSuggestionCount: number;
  onCommit: () => void;
  disabled?: boolean;
  ratify?: RatifyContext;
}

function formatSpecType(specType: string): string {
  if (specType === "prd") return "PRD";
  if (specType === "design") return "Design";
  if (specType === "rfc") return "RFC";
  if (specType.startsWith("rfc-")) return `RFC: ${specType.slice(4)}`;
  return specType.toUpperCase();
}

export function CommitBar({
  activeSpecType,
  claimState,
  validationState,
  unresolvedSuggestionCount,
  resolvedSuggestionCount,
  onCommit,
  disabled,
  ratify,
}: CommitBarProps) {
  const passCount = validationState?.passCount ?? 0;
  const warnCount = validationState?.warnCount ?? 0;
  const failCount = validationState?.failCount ?? 0;
  const hasBlockers = failCount > 0 || unresolvedSuggestionCount > 0;

  // Non-claimant modes: disabled with a reason caption, no commit allowed.
  // The "mine" and "unclaimed" variants of ClaimState are the only ones
  // that let the caller through to the commit action; every other
  // variant renders a permanently disabled button with the reason shown
  // inline.
  const nonClaimant =
    claimState.kind === "claimed-by-other" ||
    claimState.kind === "stale" ||
    claimState.kind === "committed";

  const isDisabled = disabled || hasBlockers || nonClaimant || claimState.kind === "unclaimed";

  let disabledReason: string | null = null;
  if (claimState.kind === "claimed-by-other") {
    disabledReason = `Claimed by ${claimState.claimant}`;
  } else if (claimState.kind === "stale") {
    disabledReason = `Claim stale — ${claimState.claimant} inactive`;
  } else if (claimState.kind === "committed") {
    disabledReason = `Committed by ${claimState.claimant}`;
  } else if (claimState.kind === "unclaimed") {
    disabledReason = `Claim ${formatSpecType(activeSpecType)} first`;
  }

  const blockerText = hasBlockers
    ? [
        failCount > 0 ? `${failCount} fail validation${failCount > 1 ? "s" : ""}` : "",
        unresolvedSuggestionCount > 0 ? `${unresolvedSuggestionCount} pending suggestion${unresolvedSuggestionCount > 1 ? "s" : ""}` : "",
      ].filter(Boolean).join(" and ")
    : "";

  return (
    <div
      style={{
        height: 52,
        borderTop: "1px solid var(--color-border)",
        display: "flex",
        alignItems: "center",
        padding: "0 20px",
        gap: 16,
        flexShrink: 0,
        background: "var(--color-bg-card)",
        boxShadow: "0 -2px 8px rgba(0, 0, 0, 0.3)",
      }}
    >
      {/* Scope label: SCOPE [spec_type] */}
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          fontWeight: 500,
          color: "var(--color-text-tertiary)",
          letterSpacing: "0.05em",
          textTransform: "uppercase",
        }}
      >
        SCOPE{" "}
        <span style={{ color: "var(--color-text-secondary)" }}>
          {formatSpecType(activeSpecType)}
        </span>
      </span>

      {/* Validation summary */}
      <div style={{ flex: 1, display: "flex", alignItems: "center", gap: 12 }}>
        {passCount > 0 && (
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, fontWeight: 500, display: "flex", alignItems: "center", gap: 4, color: "var(--color-emerald)" }}>
            <Check size={12} /> {passCount} pass
          </span>
        )}
        {warnCount > 0 && (
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, fontWeight: 500, display: "flex", alignItems: "center", gap: 4, color: "var(--color-amber)" }}>
            <AlertCircle size={12} /> {warnCount} warn
          </span>
        )}
        {failCount > 0 && (
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, fontWeight: 500, display: "flex", alignItems: "center", gap: 4, color: "var(--color-red)" }}>
            <AlertCircle size={12} /> {failCount} fail
          </span>
        )}

        {/* Suggestion summary */}
        {(resolvedSuggestionCount > 0 || unresolvedSuggestionCount > 0) && (
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 13, fontWeight: 500, display: "flex", alignItems: "center", gap: 4, color: unresolvedSuggestionCount > 0 ? "var(--color-amber)" : "var(--color-text-secondary)" }}>
            <MessageCircle size={14} />
            {unresolvedSuggestionCount > 0
              ? `${unresolvedSuggestionCount} unresolved`
              : `${resolvedSuggestionCount} resolved`}
          </span>
        )}
      </div>

      {/* Blocker message (blocked on validation/suggestions, not ownership) */}
      {hasBlockers && !nonClaimant && claimState.kind !== "unclaimed" && (
        <span style={{ fontSize: 11, color: "var(--color-red)" }}>
          Resolve {blockerText} to commit
        </span>
      )}

      {/* Disabled reason caption (ownership-driven) */}
      {disabledReason && (
        <span
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            color: "var(--color-text-tertiary)",
          }}
        >
          {nonClaimant && <Lock size={11} strokeWidth={2} />}
          {disabledReason}
        </span>
      )}

      {/* Commit button OR RatifyControl — the latter takes over for
          non-committer viewers of committed specs. */}
      {claimState.kind === "committed" && ratify && !ratify.viewerIsCommitter ? (
        <RatifyControl
          specType={activeSpecType}
          approvalCount={ratify.approvalCount}
          approvalThreshold={ratify.approvalThreshold}
          hasVoted={ratify.hasVoted}
          viewerVerdict={ratify.viewerVerdict}
          busy={ratify.busy}
          onApprove={ratify.onApprove}
          onReject={ratify.onReject}
        />
      ) : (
        <button
          onClick={onCommit}
          disabled={isDisabled}
          aria-label={
            isDisabled && disabledReason
              ? `Commit ${formatSpecType(activeSpecType)}, disabled — ${disabledReason}`
              : `Commit ${formatSpecType(activeSpecType)}`
          }
          style={{
            fontFamily: "var(--font-sans)", fontSize: 13, fontWeight: 600,
            background: isDisabled ? "var(--color-bg-card)" : "var(--color-accent)",
            color: isDisabled ? "var(--color-text-tertiary)" : "var(--color-bg)",
            border: isDisabled ? "1px solid var(--color-border)" : "none",
            borderRadius: 8,
            padding: "8px 20px", cursor: isDisabled ? "not-allowed" : "pointer",
            transition: "opacity 150ms",
          }}
        >
          Commit
        </button>
      )}
    </div>
  );
}
