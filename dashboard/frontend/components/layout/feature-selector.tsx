"use client";

import { useState, useMemo, useRef, useEffect } from "react";
import { useQuery } from "urql";
import * as Popover from "@radix-ui/react-popover";
import * as ScrollArea from "@radix-ui/react-scroll-area";
import { Search, ChevronDown, Layers } from "lucide-react";
import { FEATURES_QUERY } from "@/lib/graphql/queries/features";
import { useFeature } from "@/lib/hooks/use-feature-selector";
import { cn } from "@/lib/utils/cn";

interface Feature {
  name: string;
  status: string;
  taskCount: number;
}

const statusDot: Record<string, string> = {
  running: "bg-amber",
  done: "bg-emerald",
  failed: "bg-red",
  idle: "bg-text-tertiary",
};

export function FeatureSelector() {
  const { selectedFeature, setSelectedFeature } = useFeature();
  const [{ data }] = useQuery({ query: FEATURES_QUERY });
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const features: Feature[] = data?.features ?? [];

  const filtered = useMemo(() => {
    if (!search) return features;
    const q = search.toLowerCase();
    return features.filter((f) => f.name.toLowerCase().includes(q));
  }, [features, search]);

  // Focus search input when popover opens
  useEffect(() => {
    if (open) {
      // Small delay to let Radix finish mounting
      const t = setTimeout(() => inputRef.current?.focus(), 50);
      return () => clearTimeout(t);
    }
    setSearch("");
  }, [open]);

  const activeName = selectedFeature
    ? features.find((f) => f.name === selectedFeature)?.name ?? selectedFeature
    : "All features";

  const activeCount = selectedFeature
    ? features.find((f) => f.name === selectedFeature)?.taskCount
    : features.reduce((sum, f) => sum + f.taskCount, 0);

  function select(name: string | null) {
    setSelectedFeature(name);
    setOpen(false);
  }

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <button
          className={cn(
            "flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5",
            "transition-colors",
            "bg-bg-card text-text hover:bg-bg-card-hover",
            "border border-border",
            "outline-none focus-visible:ring-1 focus-visible:ring-accent/40"
          )}
        >
          <Layers className="h-3.5 w-3.5 shrink-0 text-accent" />
          <div className="flex flex-1 flex-col items-start overflow-hidden">
            <span
              className="w-full truncate text-left text-[12px] font-medium tracking-wide text-text"
              style={{ fontFamily: "var(--font-mono)" }}
            >
              {activeName}
            </span>
            {activeCount !== undefined && (
              <span className="text-[10px] text-text-tertiary">
                {activeCount} task{activeCount !== 1 ? "s" : ""}
              </span>
            )}
          </div>
          <ChevronDown
            className={cn(
              "h-3.5 w-3.5 shrink-0 text-text-tertiary transition-transform",
              open && "rotate-180"
            )}
          />
        </button>
      </Popover.Trigger>

      <Popover.Portal>
        <Popover.Content
          side="right"
          sideOffset={12}
          align="start"
          className={cn(
            "z-50 w-72 rounded-xl",
            "bg-bg-elevated border border-border",
            "shadow-[0_8px_32px_rgba(0,0,0,0.5)]",
            "animate-in fade-in-0 zoom-in-95 slide-in-from-left-2",
            "data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95"
          )}
        >
          {/* Search */}
          <div className="flex items-center gap-2 border-b border-border px-3 py-2.5">
            <Search className="h-3.5 w-3.5 shrink-0 text-text-tertiary" />
            <input
              ref={inputRef}
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search features..."
              className={cn(
                "flex-1 bg-transparent text-[12px] text-text",
                "placeholder:text-text-tertiary",
                "outline-none"
              )}
              style={{ fontFamily: "var(--font-mono)" }}
            />
          </div>

          {/* Feature list */}
          <ScrollArea.Root className="max-h-80">
            <ScrollArea.Viewport className="w-full p-1.5">
              {/* "All features" option */}
              <button
                onClick={() => select(null)}
                className={cn(
                  "flex w-full items-center gap-2.5 rounded-lg px-3 py-2 transition-colors",
                  !selectedFeature
                    ? "bg-accent/8 text-accent"
                    : "text-text-secondary hover:bg-bg-card hover:text-text"
                )}
              >
                <Layers className="h-3.5 w-3.5 shrink-0" />
                <span
                  className="text-[12px] font-medium tracking-wide"
                  style={{ fontFamily: "var(--font-mono)" }}
                >
                  All features
                </span>
                <span className="ml-auto text-[10px] text-text-tertiary">
                  {features.reduce((s, f) => s + f.taskCount, 0)}
                </span>
              </button>

              {/* Divider */}
              {filtered.length > 0 && (
                <div className="mx-3 my-1.5 h-px bg-border" />
              )}

              {/* Individual features */}
              {filtered.map((f) => (
                <button
                  key={f.name}
                  onClick={() => select(f.name)}
                  className={cn(
                    "flex w-full items-center gap-2.5 rounded-lg px-3 py-2 transition-colors",
                    selectedFeature === f.name
                      ? "bg-accent/8 text-accent"
                      : "text-text-secondary hover:bg-bg-card hover:text-text"
                  )}
                >
                  <div
                    className={cn(
                      "h-2 w-2 shrink-0 rounded-full",
                      statusDot[f.status] ?? "bg-text-tertiary"
                    )}
                  />
                  <span
                    className="flex-1 truncate text-left text-[12px] font-medium tracking-wide"
                    style={{ fontFamily: "var(--font-mono)" }}
                  >
                    {f.name}
                  </span>
                  <span className="shrink-0 text-[10px] text-text-tertiary">
                    {f.taskCount}
                  </span>
                </button>
              ))}

              {filtered.length === 0 && search && (
                <div className="px-3 py-4 text-center text-[11px] text-text-tertiary">
                  No features match "{search}"
                </div>
              )}
            </ScrollArea.Viewport>
            <ScrollArea.Scrollbar
              orientation="vertical"
              className="flex w-1.5 touch-none select-none p-0.5"
            >
              <ScrollArea.Thumb className="relative flex-1 rounded-full bg-border" />
            </ScrollArea.Scrollbar>
          </ScrollArea.Root>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
