import type { RepositoryDigestData } from "@/lib/graphql/queries/repository-digest";
import { KpiCard } from "@/components/shared/kpi-card";

export function FootprintGrid({ footprint }: { footprint: RepositoryDigestData["footprint"] }) {
  return (
    <div className="digest-kpi-grid-5">
      <KpiCard label="Files" value={footprint.fileCount.toLocaleString()} valueClassName="digest-kpi-value" />
      <KpiCard label="Lines" value={`${Math.round(footprint.lineCount / 1000)}k`} valueClassName="digest-kpi-value" />
      <KpiCard label="Languages" value={String(footprint.languages.length)} valueClassName="digest-kpi-value" />
      <KpiCard label="Areas" value={footprint.domainCount != null ? String(footprint.domainCount) : "—"} valueClassName="digest-kpi-value" />
      <KpiCard label="Symbols" value={footprint.symbolCount != null ? footprint.symbolCount.toLocaleString() : "—"} valueClassName="digest-kpi-value" />
    </div>
  );
}
