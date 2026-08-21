"use client";

interface Segment {
  value: number;
  color: string;
  label: string;
}

interface ProgressBarProps {
  segments: Segment[];
  total: number;
  height?: number;
}

export function ProgressBar({ segments, total, height = 6 }: ProgressBarProps) {
  if (total === 0) return null;

  return (
    <div className="progress-track" style={{ height }}>
      {segments.map((seg, i) => {
        const pct = (seg.value / total) * 100;
        if (pct === 0) return null;
        return (
          <div
            key={i}
            className="transition-all duration-300"
            style={{
              width: `${pct}%`,
              backgroundColor: seg.color,
              borderRadius: "inherit",
            }}
            title={`${seg.label}: ${seg.value}`}
          />
        );
      })}
    </div>
  );
}
