"use client";

import { useState } from "react";
import { usePathname } from "next/navigation";
import { GraphQLProvider } from "@/lib/graphql/provider";
import { FeatureContext } from "@/lib/hooks/use-feature-selector";
import { Sidebar } from "./sidebar";
import { Header } from "./header";

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [selectedFeature, setSelectedFeature] = useState<string | null>(null);
  const [features, setFeatures] = useState<
    Array<{ name: string; status: string; taskCount: number }>
  >([]);

  // Landing, Define, Editor, and Repository Digest render their own shell.
  // Digest is a single self-contained application (its own sidebar covers
  // its 12 screens) — it must not sit inside the global Workbench Sidebar
  // and Header, which would show as a second, competing nav column.
  if (
    pathname === "/" ||
    pathname?.startsWith("/define") ||
    pathname?.startsWith("/editor") ||
    pathname?.startsWith("/digest")
  ) {
    return (
      <GraphQLProvider>
        <FeatureContext.Provider
          value={{ selectedFeature, setSelectedFeature, features, setFeatures }}
        >
          {children}
        </FeatureContext.Provider>
      </GraphQLProvider>
    );
  }

  return (
    <GraphQLProvider>
      <FeatureContext.Provider
        value={{ selectedFeature, setSelectedFeature, features, setFeatures }}
      >
        <div className="flex h-screen overflow-hidden">
          <Sidebar />
          <div className="flex flex-1 flex-col overflow-hidden">
            <Header />
            <main className="flex-1 overflow-auto p-6">{children}</main>
          </div>
        </div>
      </FeatureContext.Provider>
    </GraphQLProvider>
  );
}
