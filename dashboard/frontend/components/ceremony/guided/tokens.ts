/** Shared visual mappings for guided authoring. Tokens only, no raw hex. */

import type { ConfidenceLabel } from "@/lib/graphql/queries/authoring";

export const CONFIDENCE_COLOR: Record<ConfidenceLabel, string> = {
  confirmed: "var(--color-emerald)",
  evidence_backed: "var(--color-blue)",
  inferred: "var(--color-violet)",
  unresolved: "var(--color-amber)",
  not_material: "var(--color-text-tertiary)",
  missing: "var(--color-red)",
};

export const CONFIDENCE_BG: Record<ConfidenceLabel, string> = {
  confirmed: "rgba(68, 204, 119, 0.12)",
  evidence_backed: "rgba(75, 166, 238, 0.12)",
  inferred: "rgba(139, 92, 246, 0.12)",
  unresolved: "rgba(240, 178, 50, 0.12)",
  not_material: "rgba(85, 85, 106, 0.12)",
  missing: "rgba(239, 68, 100, 0.12)",
};

export const SUGGESTION_COLOR: Record<string, string> = {
  grounded: "var(--color-emerald)",
  partial: "var(--color-amber)",
  missing: "var(--color-text-tertiary)",
};

export const SUGGESTION_BG: Record<string, string> = {
  grounded: "rgba(68, 204, 119, 0.12)",
  partial: "rgba(240, 178, 50, 0.12)",
  missing: "rgba(85, 85, 106, 0.12)",
};

/** Helper vocabulary is displayed, not renamed. One formatter, one wording. */
export function humanizeLabel(value: string): string {
  const spaced = value.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function middleTruncate(value: string, max = 44): string {
  if (value.length <= max) return value;
  const head = Math.ceil((max - 1) / 2);
  const tail = Math.floor((max - 1) / 2);
  return `${value.slice(0, head)}…${value.slice(value.length - tail)}`;
}
