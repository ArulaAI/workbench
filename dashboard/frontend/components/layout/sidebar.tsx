"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "urql";
import {
  House,
  LayoutDashboard,
  Network,
  BookOpen,
  FileEdit,
  CheckSquare,
  Wallet,
  BarChart3,
  GitBranch,
} from "lucide-react";
import { cn } from "@/lib/utils/cn";
import { FeatureSelector } from "./feature-selector";
import { PROJECT_QUERY } from "@/lib/graphql/queries/features";

const navItems = [
  { href: "/", label: "Home", icon: House },
  {
    href: "/mission-control",
    label: "Mission Control",
    icon: LayoutDashboard,
  },
  { href: "/topology", label: "Topology", icon: Network },
  { href: "/define", label: "Define", icon: BookOpen },
  { href: "/editor", label: "Spec Editor", icon: FileEdit },
  { href: "/spec-alignment", label: "Spec Alignment", icon: CheckSquare },
  { href: "/budget", label: "Budget", icon: Wallet },
  { href: "/analytics", label: "Analytics", icon: BarChart3 },
];

function SectionLabel({ children }: { children: string }) {
  return (
    <div className="type-table-header px-4 pb-2 pt-6 first:pt-0">
      {children}
    </div>
  );
}

function ProjectInfo() {
  const [{ data }] = useQuery({ query: PROJECT_QUERY });
  const project = data?.project;

  if (!project) {
    return (
      <div className="px-4">
        <div className="h-4 w-24 animate-pulse rounded bg-bg-card" />
      </div>
    );
  }

  const shortHead = project.gitHead?.slice(0, 7);
  // Extract branch from gitRemote or show repo name
  const repoName = project.name;

  return (
    <div className="space-y-1.5 px-4">
      <div
        className="text-[13px] font-medium text-text"
        style={{ fontFamily: "var(--font-mono)" }}
      >
        {repoName}
      </div>
      {shortHead && (
        <div className="flex items-center gap-1.5">
          <GitBranch className="h-3 w-3 text-text-tertiary" />
          <span className="text-[10px] text-text-tertiary font-mono">
            {shortHead}
          </span>
        </div>
      )}
    </div>
  );
}

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex h-screen w-60 flex-col border-r border-border bg-bg-elevated">
      {/* Brand */}
      <div className="flex h-16 items-center px-5">
        <span
          className="text-[15px] font-semibold tracking-tight text-accent"
          style={{ fontFamily: "var(--font-mono)" }}
        >
          {">"} SPEED
        </span>
      </div>

      <div className="flex-1 overflow-y-auto py-2">
        {/* Project section */}
        <SectionLabel>Project</SectionLabel>
        <ProjectInfo />

        {/* Feature section */}
        <SectionLabel>Feature</SectionLabel>
        <div className="px-3">
          <FeatureSelector />
        </div>

        {/* Navigation section */}
        <SectionLabel>Views</SectionLabel>
        <nav className="space-y-0.5 px-3">
          {navItems.map((item) => {
            const isActive = pathname === item.href;
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "group relative flex items-center gap-3 rounded-lg px-3 py-2.5 transition-colors",
                  isActive
                    ? "bg-accent-glow text-accent"
                    : "text-text-secondary hover:bg-bg-card hover:text-text"
                )}
              >
                {/* Active indicator bar */}
                {isActive && (
                  <div
                    className="absolute left-0 top-1/2 h-4 w-[3px] -translate-y-1/2 rounded-r-full bg-accent"
                    style={{ boxShadow: "0 0 8px var(--color-accent-glow)" }}
                  />
                )}
                <Icon className={cn(
                  "h-4 w-4 shrink-0 transition-colors",
                  isActive ? "text-accent" : "text-text-tertiary group-hover:text-text-secondary"
                )} />
                <span
                  className="text-[12px] font-medium tracking-wide"
                  style={{ fontFamily: "var(--font-mono)" }}
                >
                  {item.label}
                </span>
              </Link>
            );
          })}
        </nav>
      </div>

      {/* Footer */}
      <div className="border-t border-border px-5 py-4">
        <span className="type-caption">v0.1</span>
      </div>
    </aside>
  );
}
