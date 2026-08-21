"use client";

import { usePathname } from "next/navigation";
import { ConnectionStatus } from "./connection-status";

const views: Record<string, { title: string; description: string }> = {
  "/": {
    title: "Landing",
    description: "Active features, recent coverage, and escalation signals across the project.",
  },
  "/mission-control": {
    title: "Mission Control",
    description: "Task execution graph and progress for the active feature.",
  },
  "/topology": {
    title: "Codebase Topology",
    description: "Symbol distribution and dependency structure across your codebase.",
  },
  "/define": {
    title: "Define",
    description: "Spec coverage, draft specifications, and open defects for the active feature.",
  },
  "/spec-alignment": {
    title: "Spec Alignment",
    description: "How closely the implementation matches the specification, claim by claim.",
  },
  "/budget": {
    title: "Context Budget",
    description: "Token allocation per task: what the agent saw, what got cut, and how much headroom remains.",
  },
  "/analytics": {
    title: "Token Burn Analytics",
    description: "Cost, model usage, and cache efficiency across all agent runs.",
  },
};

export function Header({ actions }: { actions?: React.ReactNode }) {
  const pathname = usePathname();
  const view = views[pathname];

  return (
    <header
      className="flex items-center justify-between bg-bg-elevated px-6 py-4"
      style={{
        borderBottom: "1px solid var(--color-border)",
        boxShadow: "0 1px 3px rgba(0,0,0,0.15)",
      }}
    >
      <div>
        <div className="type-page-title">{view?.title ?? "SPEED Dashboard"}</div>
        {view?.description && (
          <div className="type-caption mt-1.5">{view.description}</div>
        )}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        {actions}
        <ConnectionStatus />
      </div>
    </header>
  );
}
