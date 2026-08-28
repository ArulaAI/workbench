import type { RepositoryDigestData } from "@/lib/graphql/queries/repository-digest";
import { KpiCard } from "@/components/shared/kpi-card";

export function FootprintGrid({ footprint }: { footprint: RepositoryDigestData["footprint"] }) {
  return (
    <div className="digest-kpi-grid">
      <KpiCard label="Files" value={footprint.fileCount.toLocaleString()} />
      <KpiCard label="Lines" value={`${Math.round(footprint.lineCount / 1000)}k`} />
      <KpiCard label="Domains" value={footprint.domainCount != null ? String(footprint.domainCount) : "—"} />
      <KpiCard label="Symbols" value={footprint.symbolCount != null ? footprint.symbolCount.toLocaleString() : "—"} />
    </div>
  );
}
