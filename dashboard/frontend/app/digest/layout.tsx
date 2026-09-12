"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { DigestSidebar } from "@/components/digest/DigestSidebar";
import { ConnectionStatus } from "@/components/layout/connection-status";
import { RepositoryDigestProvider } from "@/lib/hooks/useRepositoryDigest";

/**
 * Repository Digest is a single self-contained application shell — AppShell
 * skips the global Workbench Sidebar/Header for every /digest/* route (see
 * app-shell.tsx) so this layout owns the whole viewport: one slim topbar,
 * one Digest-specific sidebar, one scrolling content region. Nothing here
 * duplicates chrome the way the old nested Header + global Sidebar did.
 *
 * RepositoryDigestProvider lives here rather than in each page for the
 * same reason: this layout is the one thing that never unmounts across
 * a /digest/* -> /digest/* navigation, so it's the only place that can
 * hold a single, non-duplicated subscription to the digest query/status/
 * subscription operations. See useRepositoryDigest.tsx's own comment for
 * the bug this fixes (a urql + React concurrent-rendering warning caused
 * by every page previously opening its own, redundant subscription).
 */
const SCREEN_LABELS: Record<string, string> = {
  "/digest": "Overview",
  "/digest/start": "Start here",
  "/digest/architecture": "Architecture",
  "/digest/api-data": "API & data",
  "/digest/workflows": "Build & tests",
  "/digest/cicd": "CI/CD",
  "/digest/runtime": "Runtime & config",
  "/digest/security": "Security",
  "/digest/knowledge": "Team knowledge",
  "/digest/changes": "Changes",
  "/digest/coverage": "Coverage & conflicts",
  "/digest/quality": "Discovery quality",
};

export default function DigestLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const screenLabel = SCREEN_LABELS[pathname ?? ""] ?? "";
  const [navigationOpen,setNavigationOpen] = useState(false);
  useEffect(()=>setNavigationOpen(false),[pathname]);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", overflow: "hidden" }}>
      <div
        className="digest-topbar"
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          height: 56,
          flexShrink: 0,
          borderBottom: "1px solid var(--color-border)",
          background: "var(--color-bg-elevated)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <button className="digest-mobile-menu" aria-expanded={navigationOpen} aria-controls="digest-navigation" onClick={()=>setNavigationOpen(!navigationOpen)}>Sections</button>
          <Link href="/" className="digest-breadcrumb" style={{ textDecoration: "none" }}>
            Workbench
          </Link>
          <span className="digest-breadcrumb digest-product-breadcrumb">/</span>
          <span className="digest-breadcrumb digest-product-breadcrumb">Repository Digest</span>
          {screenLabel && (
            <>
              <span className="digest-breadcrumb">/</span>
              <span className="digest-breadcrumb-current">{screenLabel}</span>
            </>
          )}
        </div>
        <ConnectionStatus />
      </div>

      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        <div id="digest-navigation" className={`digest-navigation${navigationOpen ? ' is-open' : ''}`}
          onClick={event=>{if ((event.target as HTMLElement).closest('a')) setNavigationOpen(false);}}><DigestSidebar /></div>
        <main
          className="digest-content"
          style={{
            flex: 1,
            minWidth: 0,
            overflowY: "auto",
            display: "flex",
            flexDirection: "column",
            gap: 16,
          }}
        >
          <RepositoryDigestProvider>{children}</RepositoryDigestProvider>
        </main>
      </div>
    </div>
  );
}
