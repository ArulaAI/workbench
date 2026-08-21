"use client";

import { cn } from "@/lib/utils/cn";

interface SkeletonProps {
  className?: string;
}

export function Skeleton({ className }: SkeletonProps) {
  return (
    <div
      className={cn(
        "animate-pulse rounded-md bg-bg-elevated",
        className
      )}
    />
  );
}

export function CardSkeleton() {
  return (
    <div className="surface p-5">
      <Skeleton className="mb-3 h-3 w-20" />
      <Skeleton className="h-7 w-28" />
      <Skeleton className="mt-2 h-3 w-16" />
    </div>
  );
}

export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-10 w-full rounded-lg" />
      ))}
    </div>
  );
}
