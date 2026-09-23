"use client";

import { useMemo } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useClient, useQuery } from "urql";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import {
  AlertTriangle,
  ArrowLeft,
  Bug,
  Check,
  ChevronDown,
  CircleDot,
  Download,
  FileJson,
  FileText,
  Filter,
  Layers3,
  RefreshCw,
  Search,
  ShieldAlert,
  X,
} from "lucide-react";
import { Header } from "@/components/layout/header";
import { IconRail } from "@/components/landing/IconRail";
import { DefectRow } from "@/components/define/defect-row";
import type { DefectData } from "@/lib/graphql/queries/define";
import { DEFECT_REPORT_EXPORT_QUERY, DEFECT_REPORT_QUERY } from "@/lib/graphql/queries/feature-defects";

type Row = {
  slug: string; title: string; severity: string; status: string; description: string;
  impact: string | null; filed_at: string | null; updated_at: string | null;
  related_features: string[]; source: string; source_feature: string | null;
  source_finding_id: string | null;
  canonical_path: string | null; filed: boolean; warnings: string[];
};
type Report = { revision: string; rows: Row[]; groups: { feature: string; slugs: string[] }[]; totals: Record<string, number>; warnings: string[]; facets: { features: string[]; severity: string[]; status: string[]; source: string[] } };

const controlClass = "inline-flex h-9 items-center justify-center gap-2 rounded-md border border-border bg-bg-elevated px-3 text-[11px] font-medium text-text-secondary outline-none transition-all hover:border-white/15 hover:bg-bg-card-hover hover:text-text disabled:pointer-events-none disabled:opacity-35";
const iconButtonClass = "inline-flex h-9 w-9 items-center justify-center rounded-md border border-border bg-bg-elevated text-text-secondary transition-all hover:border-white/15 hover:bg-bg-card-hover hover:text-text disabled:pointer-events-none disabled:opacity-35";

const sourceLabels: Record<string, string> = {
  define: "Define",
  diagnose: "Diagnose",
  code_review: "Code review",
  structured_review: "Code review",
  clean_review: "Clean review",
  unknown: "Unknown",
};

function displayValue(value: string): string {
  if (value === "_unassigned") return "Unassigned";
  return sourceLabels[value] || value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function FilterMenu({ label, values, selected, onChange }: {
  label: string;
  values: string[];
  selected: string[];
  onChange: (values: string[]) => void;
}) {
  const options = [...new Set([...selected, ...values])];
  const toggle = (value: string) => onChange(
    selected.includes(value) ? selected.filter((item) => item !== value) : [...selected, value],
  );
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button className={controlClass} disabled={!options.length}>
          {label}
          {!!selected.length && <span className="flex h-4 min-w-4 items-center justify-center rounded-full bg-accent/10 px-1 font-mono text-[9px] text-accent">{selected.length}</span>}
          <ChevronDown className="h-3 w-3 text-text-tertiary" />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content align="start" sideOffset={6} className="z-50 min-w-48 rounded-lg border border-border bg-bg-elevated p-1.5 shadow-[0_16px_40px_rgba(0,0,0,0.45)]">
          <div className="px-2 py-1.5 text-[9px] font-semibold uppercase tracking-[0.12em] text-text-tertiary">Filter by {label.toLowerCase()}</div>
          {options.map((value) => <DropdownMenu.CheckboxItem
            key={value}
            checked={selected.includes(value)}
            onCheckedChange={() => toggle(value)}
            onSelect={(event) => event.preventDefault()}
            className="flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-2 text-[11px] text-text-secondary outline-none transition-colors data-[highlighted]:bg-bg-card-hover data-[highlighted]:text-text"
          >
            <span className={`flex h-3.5 w-3.5 items-center justify-center rounded border ${selected.includes(value) ? "border-accent/40 bg-accent/15 text-accent" : "border-white/15"}`}>
              {selected.includes(value) && <Check className="h-2.5 w-2.5" />}
            </span>
            {displayValue(value)}
          </DropdownMenu.CheckboxItem>)}
          {!!selected.length && <>
            <DropdownMenu.Separator className="my-1 h-px bg-border" />
            <DropdownMenu.Item onSelect={() => onChange([])} className="cursor-pointer rounded-md px-2.5 py-2 text-[11px] text-text-tertiary outline-none data-[highlighted]:bg-bg-card-hover data-[highlighted]:text-text">Clear {label.toLowerCase()}</DropdownMenu.Item>
          </>}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

export default function DefectReportPage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const client = useClient();
  const variables = useMemo(() => ({
    features: searchParams.getAll("feature"), severity: searchParams.getAll("severity"),
    status: searchParams.getAll("status"), source: searchParams.getAll("source"),
    lifecycle: searchParams.getAll("lifecycle"), search: searchParams.get("q") || "",
  }), [searchParams]);
  const [{ data, fetching, error }] = useQuery<{ defectReport: Report }>({ query: DEFECT_REPORT_QUERY, variables });
  const report = data?.defectReport;
  const setOne = (key: string, value: string) => {
    const next = new URLSearchParams(searchParams.toString());
    next.delete(key); if (value) next.append(key, value);
    router.replace(`/define/defects${next.size ? `?${next}` : ""}`);
  };
  const setMany = (key: string, values: string[]) => {
    const next = new URLSearchParams(searchParams.toString());
    next.delete(key); values.forEach((value) => next.append(key, value));
    router.push(`/define/defects${next.size ? `?${next}` : ""}`);
  };
  const download = async (format: "json" | "markdown") => {
    if (!report) return;
    const response = await client.query(DEFECT_REPORT_EXPORT_QUERY, { ...variables, displayedRevision: report.revision, format }, { requestPolicy: "network-only" }).toPromise();
    const result = response.data?.defectReportExport;
    if (!result?.success) { window.alert(result?.errors?.[0]?.message || "Export failed"); return; }
    const blob = new Blob([result.content], { type: format === "json" ? "application/json" : "text/markdown" });
    const url = URL.createObjectURL(blob); const anchor = document.createElement("a");
    anchor.href = url; anchor.download = `defects.${format === "json" ? "json" : "md"}`; anchor.click(); URL.revokeObjectURL(url);
  };
  const mapRow = (row: Row): DefectData => ({
    name: row.slug, title: row.title, severity: row.severity, status: row.status,
    description: row.description, impact: row.impact, filedAt: row.filed_at, updatedAt: row.updated_at,
    relatedFeatures: row.related_features, source: row.source, sourceFeature: row.source_feature,
    sourceFindingId: row.source_finding_id,
    canonicalPath: row.canonical_path, filed: row.filed, warnings: row.warnings,
  });
  const rowsBySlug = new Map(report?.rows.map((row) => [row.slug, row]) || []);
  const returnPath = `/define/defects${searchParams.size ? `?${searchParams.toString()}` : ""}`;
  const activeFilters = [
    ...variables.features.map((value) => ({ key: "feature", value, label: `Feature: ${displayValue(value)}` })),
    ...variables.severity.map((value) => ({ key: "severity", value, label: `Severity: ${value}` })),
    ...variables.lifecycle.map((value) => ({ key: "lifecycle", value, label: `Lifecycle: ${displayValue(value)}` })),
    ...variables.status.map((value) => ({ key: "status", value, label: `Status: ${displayValue(value)}` })),
    ...variables.source.map((value) => ({ key: "source", value, label: `Source: ${displayValue(value)}` })),
  ];
  const removeFilter = (key: string, value: string) => {
    const next = new URLSearchParams(searchParams.toString());
    const remaining = next.getAll(key).filter((item) => item !== value);
    next.delete(key); remaining.forEach((item) => next.append(key, item));
    router.push(`/define/defects${next.size ? `?${next}` : ""}`);
  };
  const clearFilters = () => router.push("/define/defects");
  const totals = report?.totals || {};

  return <div className="flex min-h-screen"><IconRail /><div className="min-w-0 flex-1"><Header />
    <main className="mx-auto max-w-[1180px] px-5 pb-20 pt-7 sm:px-7 lg:px-9">
      <header className="mb-7 flex flex-col justify-between gap-5 sm:flex-row sm:items-start">
        <div>
          <Link href="/define" className="mb-3 inline-flex items-center gap-1.5 text-[11px] font-medium text-text-tertiary transition-colors hover:text-text-secondary"><ArrowLeft className="h-3.5 w-3.5" /> Define</Link>
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-blue/15 bg-blue/10 text-blue shadow-[0_0_24px_rgba(75,166,238,0.06)]"><Bug className="h-5 w-5" /></div>
            <div>
              <h1 className="font-mono text-[22px] font-semibold tracking-[-0.03em] text-text">Defect report</h1>
              <p className="mt-0.5 text-[12px] text-text-secondary">Canonical reports and pipeline state across affected features.</p>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button className={controlClass} disabled={!report} onClick={() => download("markdown")}><Download className="h-3.5 w-3.5" /> Markdown</button>
          <button className={iconButtonClass} disabled={!report} aria-label="Export JSON" title="Export JSON" onClick={() => download("json")}><FileJson className="h-3.5 w-3.5" /></button>
        </div>
      </header>

      <section aria-label="Defect summary" className="mb-5 grid grid-cols-2 gap-2.5 lg:grid-cols-4">
        {[
          { label: "Total defects", value: totals.total || 0, icon: Bug, color: "var(--color-blue)", hint: `${totals.closed || 0} closed` },
          { label: "Active", value: totals.active || 0, icon: CircleDot, color: "var(--color-amber)", hint: "Requires follow-up" },
          { label: "P0–P1", value: totals.p0_p1 || 0, icon: ShieldAlert, color: "var(--color-red)", hint: "Highest priority" },
          { label: "Features", value: totals.affected_features || 0, icon: Layers3, color: "var(--color-accent)", hint: `${totals.unassigned || 0} unassigned` },
        ].map((stat) => <div key={stat.label} className="surface flex min-w-0 items-center gap-3 px-4 py-3.5">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg" style={{ color: stat.color, backgroundColor: `color-mix(in srgb, ${stat.color} 10%, transparent)` }}><stat.icon className="h-4 w-4" /></div>
          <div className="min-w-0"><div className="flex items-baseline gap-2"><span className="font-mono text-lg font-semibold tabular-nums text-text">{stat.value}</span><span className="text-[11px] font-semibold text-text-secondary">{stat.label}</span></div><div className="truncate text-[10px] text-text-tertiary">{stat.hint}</div></div>
        </div>)}
      </section>

      <section aria-label="Defect filters" className="surface mb-4 overflow-hidden">
        <div className="flex flex-col gap-3 px-3 py-3 lg:flex-row lg:items-center">
          <label className="relative min-w-0 flex-1 lg:max-w-xs">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-tertiary" />
            <input aria-label="Search defects" value={variables.search} placeholder="Search title or slug…" onChange={(event) => setOne("q", event.target.value)} className="h-9 w-full rounded-md border border-border bg-bg px-3 pl-9 text-[11px] text-text outline-none transition-colors placeholder:text-text-tertiary focus:border-accent/40 focus:ring-2 focus:ring-accent/10" />
          </label>
          <div className="flex flex-wrap items-center gap-2">
            <div className="mr-1 flex items-center gap-1.5 text-[10px] font-medium text-text-tertiary"><Filter className="h-3.5 w-3.5" /> Filters</div>
            <FilterMenu label="Feature" values={report?.facets.features || []} selected={variables.features} onChange={(values) => setMany("feature", values)} />
            <FilterMenu label="Severity" values={report?.facets.severity || ["P0", "P1", "P2", "P3", "unknown"]} selected={variables.severity} onChange={(values) => setMany("severity", values)} />
            <FilterMenu label="Lifecycle" values={["active", "closed"]} selected={variables.lifecycle} onChange={(values) => setMany("lifecycle", values)} />
            <FilterMenu label="Status" values={report?.facets.status || []} selected={variables.status} onChange={(values) => setMany("status", values)} />
            <FilterMenu label="Source" values={report?.facets.source || []} selected={variables.source} onChange={(values) => setMany("source", values)} />
          </div>
        </div>
        {(activeFilters.length > 0 || variables.search) && <div className="flex flex-wrap items-center gap-2 border-t border-border px-4 py-2.5">
          <span className="mr-1 text-[10px] text-text-tertiary">Active</span>
          {activeFilters.map((filter) => <button key={`${filter.key}:${filter.value}`} onClick={() => removeFilter(filter.key, filter.value)} className="inline-flex items-center gap-1.5 rounded-full border border-accent/15 bg-accent/5 px-2.5 py-1 text-[10px] font-medium text-accent transition-colors hover:bg-accent/10">{filter.label}<X className="h-2.5 w-2.5" /></button>)}
          {variables.search && <button onClick={() => setOne("q", "")} className="inline-flex items-center gap-1.5 rounded-full border border-accent/15 bg-accent/5 px-2.5 py-1 text-[10px] font-medium text-accent transition-colors hover:bg-accent/10">Search: “{variables.search}”<X className="h-2.5 w-2.5" /></button>}
          <button onClick={clearFilters} className="ml-auto text-[10px] font-medium text-text-tertiary hover:text-text">Clear all</button>
        </div>}
      </section>

      {error && <div role="alert" className="mb-3 rounded-lg border border-red/20 bg-red/5 px-3 py-2.5 text-[11px] text-red">{error.message}</div>}
      {report?.warnings.map((warning) => <div role="alert" key={warning} className="mb-3 flex items-center gap-2 rounded-lg border border-amber/20 bg-amber/5 px-3 py-2.5 text-[11px] text-amber"><AlertTriangle className="h-3.5 w-3.5" /> {warning}</div>)}

      {fetching && !report && <div className="surface flex items-center justify-center gap-2 py-20 text-[12px] text-text-secondary"><RefreshCw className="h-4 w-4 animate-spin" /> Loading defect inventory…</div>}
      {report && !report.rows.length && <div className="surface flex flex-col items-center px-6 py-20 text-center">
        <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-xl border border-border bg-bg-elevated text-text-tertiary">{activeFilters.length || variables.search ? <Filter className="h-5 w-5" /> : <FileText className="h-5 w-5" />}</div>
        <h2 className="text-[14px] font-semibold text-text">{activeFilters.length || variables.search ? "No defects match this view" : "No defects filed yet"}</h2>
        <p className="mt-1 max-w-md text-[11px] leading-5 text-text-tertiary">{activeFilters.length || variables.search ? "The inventory is healthy; the active filters simply returned no records." : "Defects filed from a feature’s finding inbox will appear here with their canonical report and pipeline status."}</p>
        {activeFilters.length || variables.search ? <button onClick={clearFilters} className="mt-5 inline-flex h-9 items-center gap-2 rounded-md bg-accent px-3.5 text-[11px] font-semibold text-[#07130f] hover:brightness-110"><X className="h-3.5 w-3.5" /> Clear filters</button> : null}
      </div>}

      {!!report?.rows.length && <div role="table" aria-label="Defects" className="surface overflow-x-auto">
        <div role="row" className="grid min-w-[800px] grid-cols-[80px_120px_minmax(260px,1fr)_220px_130px] border-b border-border bg-bg-elevated/60">
          {['Severity', 'Status', 'Defect', 'Affected features', 'Source'].map((heading) => <div role="columnheader" key={heading} className="type-table-header px-4 py-2.5">{heading}</div>)}
        </div>
        <div className="min-w-[800px]">{variables.features.length > 0
          ? report.rows.map((row) => <DefectRow key={row.slug} defect={mapRow(row)} mode="table" returnPath={returnPath} />)
          : report.groups.flatMap((group) => [
              <div role="row" key={`group-${group.feature}`} className="flex items-center gap-2 border-b border-border bg-bg/60 px-4 py-2 font-mono text-[9px] font-semibold uppercase tracking-[0.1em] text-text-tertiary"><Layers3 className="h-3 w-3" />{displayValue(group.feature)}<span className="rounded-full bg-bg-card px-1.5 py-0.5 text-[8px]">{group.slugs.length}</span></div>,
              ...group.slugs.map((slug) => rowsBySlug.get(slug)).filter((row): row is Row => Boolean(row)).map((row) => <DefectRow key={row.slug} defect={mapRow(row)} mode="table" returnPath={returnPath} />),
            ])}</div>
      </div>}
    </main></div></div>;
}
