"use client";

import { Lock, Clock } from "lucide-react";

/**
 * ReadOnlyBanner — top-of-editor banner shown to non-claimants of the
 * active spec.
 *
 * Two variants per the Design spec:
 *   standard — grey left-border, lock glyph, "Claimed by {name}"
 *   stale    — amber left-border, clock glyph, takeover invitation
 *
 * Same shape, different color/message/glyph. The Design spec "no pure
 * white" + "depth comes in pairs: border + shadow" rules apply; the
 * banner sits on `bg-card` with a left accent bar (color only, no
 * outline border) so the editor body beneath remains visually primary.
 */

interface ReadOnlyBannerProps {
  kind: "standard" | "stale";
  claimant: string;
  staleFor?: string;
  onTakeover?: () => void;
}

export function ReadOnlyBanner({
  kind,
  claimant,
  staleFor,
  onTakeover,
}: ReadOnlyBannerProps) {
  const isStale = kind === "stale";
  const borderColor = isStale ? "var(--color-amber)" : "var(--color-text-tertiary)";
  const glyphColor = borderColor;
  const Glyph = isStale ? Clock : Lock;

  return (
    <div
      className="read-only-banner"
      role="status"
      aria-live="polite"
      style={{
        borderLeft: `2px solid ${borderColor}`,
      }}
    >
      <style>{STYLES}</style>
      <Glyph
        size={13}
        strokeWidth={2}
        style={{ color: glyphColor, flexShrink: 0 }}
      />
      <span className="read-only-banner-text">
        {isStale ? (
          <>
            <strong>{claimant}</strong> has been inactive
            {staleFor ? ` for ${staleFor}` : ""}
            {onTakeover && (
              <>
                {" · "}
                <button
                  className="read-only-banner-takeover"
                  onClick={onTakeover}
                  aria-label={`Take over stale claim from ${claimant}`}
                >
                  click Claim to take over
                </button>
              </>
            )}
          </>
        ) : (
          <>
            Read-only · claimed by <strong>{claimant}</strong>
          </>
        )}
      </span>
    </div>
  );
}

const STYLES = `
  .read-only-banner {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 14px;
    margin-bottom: 20px;
    background: var(--color-bg-card);
    border-radius: 0 4px 4px 0;
    font-family: var(--font-sans);
    font-size: 13px;
    font-weight: 400;
    line-height: 1.5;
    color: var(--color-text-secondary);
  }
  .read-only-banner-text strong {
    color: var(--color-text);
    font-weight: 600;
  }
  .read-only-banner-takeover {
    background: none;
    border: none;
    padding: 0;
    font: inherit;
    color: var(--color-amber);
    cursor: pointer;
    text-decoration: none;
  }
  .read-only-banner-takeover:hover {
    text-decoration: underline;
  }
  .read-only-banner-takeover:focus-visible {
    outline: 2px solid var(--color-amber);
    outline-offset: 2px;
    border-radius: 2px;
  }
`;
