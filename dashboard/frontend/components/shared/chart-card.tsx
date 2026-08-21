"use client";

import { cn } from "@/lib/utils/cn";

interface ChartCardProps {
  title: string;
  children: React.ReactNode;
  className?: string;
}

export function ChartCard({ title, children, className }: ChartCardProps) {
  return (
    <div className={cn("surface p-5", className)}>
      <h3 className="type-section-header mb-4">{title}</h3>
      {children}
    </div>
  );
}
