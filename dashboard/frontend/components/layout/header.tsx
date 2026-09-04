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
  "/digest": {
    title: "Repository Digest",
    description: "A synthesized snapshot of the repository: domains, hotspots, commands, and conventions.",
  },
  "/digest/workflows": {
    title: "Repository Digest — Build & tests",
    description: "Discovered commands grouped by working directory, and known test suites.",
  },
  "/digest/quality": {
    title: "Repository Digest — Discovery quality",
    description: "Readiness by capability and warnings raised during the last build.",
  },
  "/digest/start": {
    title: "Repository Digest — Start here",
    description: "Entrypoints, repository structure, and a deterministic suggested reading path.",
  },
  "/digest/knowledge": {
    title: "Repository Digest — Team knowledge",
    description: "Approved conventions and project knowledge, pending drafts, and recurring signals.",
  },
  "/digest/coverage": {
    title: "Repository Digest — Coverage & conflicts",
    description: "How much of the repository discovery actually covers, and where sources disagree.",
  },
  "/digest/architecture": {
    title: "Repository Digest — Architecture",
    description: "Domains grouped into lanes, and the verified relationships discovered between them.",
  },
  "/digest/api-data": {
    title: "Repository Digest — API & Data",
    description: "Discovered API routes, ORM entities, and persistence information.",
  },
  "/digest/cicd": {
    title: "Repository Digest — CI/CD",
    description: "Discovered CI/CD pipelines, jobs, triggers, and commands.",
  },
  "/digest/runtime": {
    title: "Repository Digest — Runtime & Configuration",
    description: "Detected language runtimes, frameworks, configuration sources, and environment variable names.",
  },
  "/digest/security": {
    title: "Repository Digest — Security",
    description: "Secret indicators, sensitive configuration, and authentication signals discovered from repository evidence.",
  },
  "/digest/changes": {
    title: "Repository Digest — Changes",
    description: "What changed since the previous digest snapshot, section by section.",
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
