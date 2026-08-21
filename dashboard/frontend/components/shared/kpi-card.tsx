"use client";

import { cn } from "@/lib/utils/cn";

interface KpiCardProps {
  label: string;
  value: string;
  sublabel?: string;
  accent?: string;
  className?: string;
}

export function KpiCard({ label, value, sublabel, accent, className }: KpiCardProps) {
  return (
    <div className={cn("surface p-5", className)}>
      <div className="type-kpi-label">{label}</div>
      <div
        className="type-kpi-value mt-1"
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
