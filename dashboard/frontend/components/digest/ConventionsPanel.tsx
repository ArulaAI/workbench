import type { DigestConvention, DigestGap } from "@/lib/graphql/queries/repository-digest";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { EvidenceAffordance } from "./EvidencePanel";

/** Renders the page layout's "Conventions and discovery gaps" row —
 * approved conventions on the left, explicit unknowns/ambiguities on the
 * right. See RFC > Dashboard Design > Page layout and > Builder Design >
 * Conventions / Gaps.
 */
export function ConventionsPanel({
  conventions,
  gaps,
}: {
  conventions: DigestConvention[];
  gaps: DigestGap[];
}) {
  return (
    <div className="surface digest-two-col" style={{ padding: 20, gap: 24 }}>
      <div>
        <div className="type-section-title" style={{ marginBottom: 12 }}>
          Conventions
        </div>
        {conventions.length === 0 ? (
          <p className="type-body">No approved conventions available.</p>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {conventions.map((c, i) => (
              <div key={i}>
                <p className="type-body" style={{ margin: 0 }}>
                  {c.text}
                </p>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4 }}>
                  <ConfidenceBadge confidence={c.confidence} />
                  {c.scope.length > 0 && (
                    <span className="type-caption">{c.scope.join(", ")}</span>
                  )}
                  <EvidenceAffordance evidence={c.evidence} />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
      <div>
        <div className="type-section-title" style={{ marginBottom: 12 }}>
          Discovery gaps
        </div>
        {gaps.length === 0 ? (
          <p className="type-body">No unresolved ambiguities.</p>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {gaps.map((g, i) => (
              <p key={i} className="type-body" style={{ margin: 0 }}>
                {g.description}
              </p>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
