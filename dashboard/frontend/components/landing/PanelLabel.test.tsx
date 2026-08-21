import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PanelLabel } from "@/components/landing/PanelLabel";

describe("PanelLabel", () => {
  it("renders name and subtitle", () => {
    render(<PanelLabel name="Define" subtitle="Specs and preparation" />);
    expect(screen.getByText("Define")).toBeInTheDocument();
    expect(screen.getByText("Specs and preparation")).toBeInTheDocument();
  });

  it("renders arbitrary name and subtitle props", () => {
    render(<PanelLabel name="Judge" subtitle="Feature name" />);
    expect(screen.getByText("Judge")).toBeInTheDocument();
    expect(screen.getByText("Feature name")).toBeInTheDocument();
  });
});
