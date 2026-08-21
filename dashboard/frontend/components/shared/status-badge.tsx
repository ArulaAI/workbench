"use client";

import { statusColors, statusBg } from "@/lib/utils/colors";

interface StatusBadgeProps {
  status: string;
  size?: "sm" | "md";
}

export function StatusBadge({ status, size = "sm" }: StatusBadgeProps) {
  const color = statusColors[status] ?? statusColors.pending;
  const bg = statusBg[status] ?? statusBg.pending;

  return (
    <span
      className={`type-badge inline-flex items-center gap-1.5 rounded-full ${
        size === "sm" ? "px-2 py-0.5" : "px-3 py-1"
      }`}
      style={{ color, backgroundColor: bg }}
    >
      <span
        className="h-1.5 w-1.5 rounded-full"
        style={{ backgroundColor: color }}
      />
      {status}
    </span>
  );
}
