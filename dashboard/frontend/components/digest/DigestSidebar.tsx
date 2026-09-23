"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutGrid,
  Compass,
  Network,
  Database,
  Terminal,
  Workflow,
  Settings2,
  ShieldCheck,
  BookOpen,
  History,
  PieChart,
  CheckSquare,
} from "lucide-react";
import { cn } from "@/lib/utils/cn";

/**
 * The full information architecture the manager's reference calls for.
 * `href: null` means "not implemented yet" — rendered disabled rather
 * than routed, so the shell can grow into these screens later without a
 * redesign, and nothing here silently claims to be a working page.
 */
const navItems: { label: string; href: string | null; icon: typeof LayoutGrid }[] = [
  { label: "Overview", href: "/digest", icon: LayoutGrid },
  { label: "Start here", href: "/digest/start", icon: Compass },
  { label: "Architecture", href: "/digest/architecture", icon: Network },
  { label: "API & data", href: "/digest/api-data", icon: Database },
  { label: "Build & tests", href: "/digest/workflows", icon: Terminal },
  { label: "CI/CD", href: "/digest/cicd", icon: Workflow },
  { label: "Runtime & config", href: "/digest/runtime", icon: Settings2 },
  { label: "Security", href: "/digest/security", icon: ShieldCheck },
  { label: "Team knowledge", href: "/digest/knowledge", icon: BookOpen },
  { label: "Changes", href: "/digest/changes", icon: History },
  { label: "Coverage & conflicts", href: "/digest/coverage", icon: PieChart },
  { label: "Discovery quality", href: "/digest/quality", icon: CheckSquare },
];

export function DigestSidebar() {
  const pathname = usePathname();

  return (
    <nav
      aria-label="Repository Digest"
      className="flex h-full shrink-0 flex-col gap-0.5 overflow-y-auto border-r border-border px-3 py-5"
      style={{ width: 230 }}
    >
      <div
        className="type-caption px-3 pb-3"
        style={{ color: "var(--color-text-tertiary)", fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase" }}
      >
        Repository Digest
      </div>
      {navItems.map((item) => {
        const Icon = item.icon;
        if (!item.href) {
          return (
            <div
              key={item.label}
              aria-disabled="true"
              title="Not yet implemented"
              className="flex items-center justify-between gap-2 rounded-lg px-3 py-2 text-text-tertiary opacity-60"
            >
              <span className="flex items-center gap-3">
                <Icon className="h-4 w-4 shrink-0" />
                <span className="text-[13px] font-medium">{item.label}</span>
              </span>
              <span className="type-caption whitespace-nowrap">Soon</span>
            </div>
          );
        }

        const isActive = pathname === item.href;
        return (
          <Link
            key={item.href}
            href={item.href}
            className={cn(
              "group relative flex items-center gap-3 rounded-lg px-3 py-2 transition-colors",
              isActive
                ? "bg-accent-glow text-accent"
                : "text-text-secondary hover:bg-bg-card hover:text-text"
            )}
          >
            {isActive && (
              <div
                className="absolute left-0 top-1/2 h-4 w-[3px] -translate-y-1/2 rounded-r-full bg-accent"
                style={{ boxShadow: "0 0 8px var(--color-accent-glow)" }}
              />
            )}
            <Icon
              className={cn(
                "h-4 w-4 shrink-0 transition-colors",
                isActive ? "text-accent" : "text-text-tertiary group-hover:text-text-secondary"
              )}
            />
            <span className="text-[12px] font-medium">{item.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
