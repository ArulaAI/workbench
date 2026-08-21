"use client";

import { Lock } from "lucide-react";

/**
 * TabClaimBadge — renders the claim chrome for one editor tab.
 *
 * Five variants matching the discriminated union in the design spec:
 *   unclaimed       — dashed Claim button, no claimant text
 *   mine            — accent claimant name, Release on hover
 *   claimed-by-other — tertiary claimant text with lock glyph
 *   stale           — amber claimant text + Takeover button
 *   committed       — static claimant text, ratified-if-true subtle tint
 *
 * The claimed-by-other variant carries a `committed` flag that changes the
 * glyph color; the committed variant carries a `ratified` flag that adds
 * an emerald tint to the claimant color.
 *
 * Per the CLAUDE.md design rules: accent reserved for mine-state, amber
 * reserved for stale, depth via shadow+border (no borderless cards).
 */

export type ClaimState =
  | { kind: "unclaimed" }
  | { kind: "mine"; claimant: string }
  | { kind: "claimed-by-other"; claimant: string; committed: boolean }
  | { kind: "stale"; claimant: string; staleFor: string }
  | { kind: "committed"; claimant: string; ratified: boolean };

interface TabClaimBadgeProps {
  state: ClaimState;
  onClaim?: () => void;
  onRelease?: () => void;
  busy?: boolean;
}

const CLAIMANT_MAX_CHARS = 12;

function truncate(name: string): string {
  if (name.length <= CLAIMANT_MAX_CHARS) return name;
  return name.slice(0, CLAIMANT_MAX_CHARS - 1) + "…";
}

export function TabClaimBadge({
  state,
  onClaim,
  onRelease,
  busy,
}: TabClaimBadgeProps) {
  if (state.kind === "unclaimed") {
    return (
      <button
        className="tab-claim-btn tab-claim-btn--unclaimed"
        onClick={(e) => {
          e.stopPropagation();
          if (!busy) onClaim?.();
        }}
        aria-label="Claim spec"
        disabled={busy}
        data-claim-btn="unclaimed"
      >
        <style>{STYLES}</style>
        {busy ? "…" : "Claim"}
      </button>
    );
  }

  if (state.kind === "mine") {
    return (
      <span className="tab-claim tab-claim--mine" aria-label="Owned by you">
        <style>{STYLES}</style>
        <span className="tab-claim-name" title={state.claimant}>
          {truncate(state.claimant)}
        </span>
        {onRelease && (
          <button
            className="tab-claim-release"
            onClick={(e) => {
              e.stopPropagation();
              if (!busy) onRelease();
            }}
            aria-label="Release claim"
            title="Release claim"
            disabled={busy}
            data-release-btn
          >
            {busy ? "…" : "Release"}
          </button>
        )}
      </span>
    );
  }

  if (state.kind === "claimed-by-other") {
    const glyphColor = state.committed
      ? "var(--color-accent)"
      : "var(--color-text-tertiary)";
    return (
      <span
        className="tab-claim tab-claim--other"
        aria-label={`Claimed by ${state.claimant}, read-only`}
        title={`Claimed by ${state.claimant}`}
      >
        <style>{STYLES}</style>
        <Lock size={10} strokeWidth={2} style={{ color: glyphColor, flexShrink: 0 }} />
        <span className="tab-claim-name">
          {truncate(state.claimant)}
        </span>
      </span>
    );
  }

  if (state.kind === "stale") {
    return (
      <span
        className="tab-claim tab-claim--stale"
        role="status"
        aria-live="polite"
        aria-label={`Stale claim, takeover available (${state.staleFor} inactive)`}
      >
        <style>{STYLES}</style>
        <span className="tab-claim-name" title={state.claimant}>
          {truncate(state.claimant)}
        </span>
        <span className="tab-stale-pill">{state.staleFor}</span>
        <button
          className="tab-claim-btn tab-claim-btn--takeover"
          onClick={(e) => {
            e.stopPropagation();
            if (!busy) onClaim?.();
          }}
          aria-label={`Take over stale claim from ${state.claimant}`}
          disabled={busy}
          data-takeover-btn
        >
          {busy ? "…" : "Takeover"}
        </button>
      </span>
    );
  }

  // committed
  const ratifiedTint = state.ratified
    ? "var(--color-emerald)"
    : "var(--color-accent)";
  return (
    <span
      className="tab-claim tab-claim--committed"
      aria-label={`Committed by ${state.claimant}${state.ratified ? ", ratified" : ""}`}
      title={`Committed by ${state.claimant}`}
    >
      <style>{STYLES}</style>
      <span className="tab-claim-name" style={{ color: ratifiedTint }}>
        {truncate(state.claimant)}
      </span>
    </span>
  );
}

const STYLES = `
  .tab-claim {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-family: var(--font-sans);
    font-size: 11px;
    font-weight: 400;
    line-height: 1.4;
    flex-shrink: 0;
    min-width: 0;
  }
  .tab-claim-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .tab-claim--mine .tab-claim-name {
    color: var(--color-accent);
  }
  .tab-claim--other .tab-claim-name {
    color: var(--color-text-tertiary);
  }
  .tab-claim--stale .tab-claim-name {
    color: var(--color-amber);
  }
  .tab-claim-release {
    font-family: var(--font-mono);
    font-size: 9px;
    font-weight: 500;
    line-height: 1.4;
    padding: 3px 8px;
    background: transparent;
    border: 1px dashed var(--color-border-strong, var(--color-text-tertiary));
    border-radius: 3px;
    color: var(--color-text-tertiary);
    cursor: pointer;
    opacity: 0;
    transition: opacity 150ms ease, border-color 150ms ease, color 150ms ease;
    flex-shrink: 0;
  }
  .tab-claim--mine:hover .tab-claim-release,
  .tab-claim-release:focus-visible {
    opacity: 1;
  }
  .tab-claim-release:hover {
    border-color: var(--color-red);
    color: var(--color-red);
  }
  .tab-claim-release:disabled {
    cursor: not-allowed;
    opacity: 0.5;
  }
  .tab-claim-btn {
    font-family: var(--font-mono);
    font-size: 9px;
    font-weight: 500;
    line-height: 1.4;
    padding: 3px 10px;
    border-radius: 3px;
    cursor: pointer;
    flex-shrink: 0;
    transition: background 150ms ease, border-color 150ms ease, color 150ms ease, transform 100ms ease;
  }
  .tab-claim-btn--unclaimed {
    background: transparent;
    border: 1px dashed var(--color-border-strong, var(--color-text-tertiary));
    color: var(--color-text-secondary);
  }
  .tab-claim-btn--unclaimed:hover {
    border-color: var(--color-accent);
    color: var(--color-accent);
  }
  .tab-claim-btn--unclaimed:focus-visible {
    outline: 2px solid var(--color-accent);
    outline-offset: 2px;
  }
  .tab-claim-btn--unclaimed:active {
    transform: scale(0.97);
  }
  .tab-claim-btn--takeover {
    background: var(--color-amber-glow, rgba(240, 178, 50, 0.12));
    border: 1px solid var(--color-amber);
    color: var(--color-amber);
    font-weight: 600;
  }
  .tab-claim-btn--takeover:hover {
    background: rgba(240, 178, 50, 0.18);
  }
  .tab-claim-btn--takeover:focus-visible {
    outline: 2px solid var(--color-amber);
    outline-offset: 2px;
  }
  .tab-claim-btn--takeover:active {
    transform: scale(0.97);
  }
  .tab-claim-btn:disabled {
    cursor: not-allowed;
    opacity: 0.6;
  }
  .tab-stale-pill {
    font-family: var(--font-mono);
    font-size: 9px;
    font-weight: 600;
    padding: 2px 7px;
    background: var(--color-amber-glow, rgba(240, 178, 50, 0.12));
    border: 1px solid rgba(240, 178, 50, 0.3);
    border-radius: 10px;
    color: var(--color-amber);
    line-height: 1.4;
    flex-shrink: 0;
  }
`;
