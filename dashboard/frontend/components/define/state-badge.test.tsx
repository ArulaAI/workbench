import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StateBadge } from "@/components/define/state-badge";

describe("StateBadge", () => {
  it("renders COMPLETE label for complete state", () => {
    render(<StateBadge state="complete" />);
    expect(screen.getByText("COMPLETE")).toBeInTheDocument();
  });

  it("renders EXECUTING label for executing state", () => {
    render(<StateBadge state="executing" />);
    expect(screen.getByText("EXECUTING")).toBeInTheDocument();
  });

  it("renders WRITING label for writing state", () => {
    render(<StateBadge state="writing" />);
    expect(screen.getByText("WRITING")).toBeInTheDocument();
  });

  it("renders UNPLANNED label for unplanned state", () => {
    render(<StateBadge state="unplanned" />);
    expect(screen.getByText("UNPLANNED")).toBeInTheDocument();
  });

  it("complete state uses emerald color", () => {
    render(<StateBadge state="complete" />);
    expect(screen.getByText("COMPLETE")).toHaveStyle({
      color: "var(--color-emerald)",
    });
  });

  it("executing state uses accent color", () => {
    render(<StateBadge state="executing" />);
    expect(screen.getByText("EXECUTING")).toHaveStyle({
      color: "var(--color-accent)",
    });
  });

  it("writing state uses amber color", () => {
    render(<StateBadge state="writing" />);
    expect(screen.getByText("WRITING")).toHaveStyle({
      color: "var(--color-amber)",
    });
  });

  it("unplanned state uses tertiary text color", () => {
    render(<StateBadge state="unplanned" />);
    expect(screen.getByText("UNPLANNED")).toHaveStyle({
      color: "var(--color-text-tertiary)",
    });
  });

  it("uses monospace font", () => {
    render(<StateBadge state="complete" />);
    expect(screen.getByText("COMPLETE")).toHaveStyle({
      fontFamily: "var(--font-mono)",
    });
  });

  it("uses 8px font size and weight 600", () => {
    render(<StateBadge state="complete" />);
    const badge = screen.getByText("COMPLETE");
    expect(badge).toHaveStyle({ fontSize: "8px", fontWeight: "600" });
  });
});
