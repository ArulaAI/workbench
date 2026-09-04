"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
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

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", overflow: "hidden" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          height: 56,
          flexShrink: 0,
          padding: "0 24px",
          borderBottom: "1px solid var(--color-border)",
          background: "var(--color-bg-elevated)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Link href="/" className="digest-breadcrumb" style={{ textDecoration: "none" }}>
            Workbench
          </Link>
          <span className="digest-breadcrumb">/</span>
          <span className="digest-breadcrumb">Repository Digest</span>
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
        <DigestSidebar />
        <main
          style={{
            flex: 1,
            minWidth: 0,
            overflowY: "auto",
            padding: 28,
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
