export const statusColors: Record<string, string> = {
  done: "var(--color-emerald)",
  running: "var(--color-amber)",
  failed: "var(--color-red)",
  pending: "var(--color-text-tertiary)",
  reviewing: "var(--color-blue)",
  idle: "var(--color-text-tertiary)",
};

export const statusBg: Record<string, string> = {
  done: "rgba(68, 204, 119, 0.12)",
  running: "rgba(240, 178, 50, 0.12)",
  failed: "rgba(239, 68, 100, 0.12)",
  pending: "rgba(85, 85, 106, 0.12)",
  reviewing: "rgba(75, 166, 238, 0.12)",
};

export function coverageColor(pct: number): string {
  if (pct >= 80) return "var(--color-emerald)";
  if (pct >= 50) return "var(--color-amber)";
  return "var(--color-red)";
}

// Accent first, violet second, then semantic colors
export const chartColors = [
  "#00d4aa",
  "#8b5cf6",
  "#4ba6ee",
  "#f0b232",
  "#44cc77",
  "#ef4464",
  "#ff6699",
  "#44ddee",
  "#e4e4e9",
  "#9494a3",
];
