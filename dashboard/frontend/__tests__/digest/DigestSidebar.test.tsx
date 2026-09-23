import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("next/navigation", () => ({
  usePathname: () => "/digest/workflows",
}));

import { DigestSidebar } from "@/components/digest/DigestSidebar";

describe("DigestSidebar", () => {
  it("renders all 12 screens from the manager reference's information architecture", () => {
    render(<DigestSidebar />);
    for (const label of [
      "Overview", "Start here", "Architecture", "API & data", "Build & tests", "CI/CD",
      "Runtime & config", "Security", "Team knowledge", "Changes", "Coverage & conflicts", "Discovery quality",
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("renders all twelve screens as real navigable links now that Phase 5B is complete", () => {
    render(<DigestSidebar />);
    expect(screen.getByText("Overview").closest("a")).toHaveAttribute("href", "/digest");
    expect(screen.getByText("Start here").closest("a")).toHaveAttribute("href", "/digest/start");
    expect(screen.getByText("Architecture").closest("a")).toHaveAttribute("href", "/digest/architecture");
    expect(screen.getByText("API & data").closest("a")).toHaveAttribute("href", "/digest/api-data");
    expect(screen.getByText("Build & tests").closest("a")).toHaveAttribute("href", "/digest/workflows");
    expect(screen.getByText("CI/CD").closest("a")).toHaveAttribute("href", "/digest/cicd");
    expect(screen.getByText("Runtime & config").closest("a")).toHaveAttribute("href", "/digest/runtime");
    expect(screen.getByText("Security").closest("a")).toHaveAttribute("href", "/digest/security");
    expect(screen.getByText("Team knowledge").closest("a")).toHaveAttribute("href", "/digest/knowledge");
    expect(screen.getByText("Changes").closest("a")).toHaveAttribute("href", "/digest/changes");
    expect(screen.getByText("Coverage & conflicts").closest("a")).toHaveAttribute("href", "/digest/coverage");
    expect(screen.getByText("Discovery quality").closest("a")).toHaveAttribute("href", "/digest/quality");
  });

  it("marks the current route active", () => {
    render(<DigestSidebar />);
    expect(screen.getByText("Build & tests").closest("a")).toHaveClass("text-accent");
  });

  it("renders no remaining disabled screens", () => {
    render(<DigestSidebar />);
    expect(screen.queryAllByText("Soon").length).toBe(0);
  });
});
