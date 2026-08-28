import type { DigestDomain } from "@/lib/graphql/queries/repository-digest";

/** Compact domain-name strip linking into Topology for full graph
 * exploration, rather than a full force-directed graph rendered here.
 */
export function SystemMap({ domains }: { domains: DigestDomain[] }) {
  return (
    <div className="surface" style={{ padding: 20 }}>
      <div className="type-section-title" style={{ marginBottom: 12 }}>
        System map
      </div>
      {domains.length === 0 ? (
        <p className="type-body">Not available until the semantic graph is built.</p>
      ) : (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {domains.map((d) => (
            <a
              key={d.id}
              href={`/topology?cluster=${encodeURIComponent(d.id)}`}
              className="type-badge"
              style={{
                padding: "8px 12px",
                borderRadius: 999,
                border: "1px solid var(--color-border)",
                color: "var(--color-text-secondary)",
                textDecoration: "none",
              }}
              title={`${d.fileCount} files, ${d.dependsOn.length + d.usedBy.length} cross-domain edges`}
            >
              {d.label}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
