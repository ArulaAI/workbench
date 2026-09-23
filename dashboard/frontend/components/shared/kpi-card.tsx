"use client";

import { cn } from "@/lib/utils/cn";

interface KpiCardProps {
  label: string;
  value: string;
  sublabel?: string;
  accent?: string;
  className?: string;
  /** Overrides the default (mono) value typography — e.g. "digest-kpi-value". */
  valueClassName?: string;
}

export function KpiCard({ label, value, sublabel, accent, className, valueClassName }: KpiCardProps) {
  return (
    <div className={cn("surface p-5", className)}>
      <div className="type-kpi-label">{label}</div>
      <div
        className={cn(valueClassName ?? "type-kpi-value", "mt-1")}
        style={{ color: accent ?? "var(--color-text)" }}
      >
        {value}
      </div>
      {sublabel && (
        <div className="type-caption mt-1">{sublabel}</div>
      )}
    </div>
  );
}
