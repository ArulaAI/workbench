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

  // Landing, Define, and Editor pages render their own shell
  if (pathname === "/" || pathname?.startsWith("/define") || pathname?.startsWith("/editor")) {
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
