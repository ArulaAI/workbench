import type { DraftView } from "@/lib/graphql/queries/feature-defects";

export function canFileDefectDraft(
  draft: DraftView["draft"] | null,
  rationale: string,
  duplicateCount: number,
  duplicateReason: string,
): boolean {
  if (!draft || !draft.title.trim() || draft.title.length > 160 || !draft.severity_confirmed) return false;
  if (!(["P0", "P1", "P2", "P3"] as Array<string>).includes(draft.severity || "")) return false;
  if (!draft.related_features.length || draft.related_features.length > 20) return false;
  if (!/^(always|once|intermittent \((?:[1-9]|10)\/10\))$/i.test(draft.reproducibility.trim())) return false;
  if (!/^1[.)]\s/.test(draft.reproduction.trim())) return false;
  if ([draft.observed, draft.expected, draft.last_known_working, draft.environment, draft.error_output, draft.context]
    .some((value) => !value.trim())) return false;
  if (!rationale.trim() || (duplicateCount > 0 && !duplicateReason.trim())) return false;
  return true;
}
