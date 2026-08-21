import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { RefMarker } from "@/components/define/ref-marker";

describe("RefMarker", () => {
  it("renders the marker number", () => {
    render(<RefMarker number={1} description="Missing auth check" />);
    expect(screen.getByText("1")).toBeInTheDocument();
  });

  it("renders aria-label referencing the number", () => {
    render(<RefMarker number={3} description="Unhandled edge case" />);
    const el = screen.getByRole("img");
    expect(el).toHaveAttribute(
      "aria-label",
      "Cross-reference 3: links audit warning to gap escalation",
    );
  });

  it("sets title attribute to description for tooltip", () => {
    render(<RefMarker number={2} description="Race condition in payment flow" />);
    const el = screen.getByRole("img");
    expect(el).toHaveAttribute("title", "Race condition in payment flow");
  });

  it("renders with amber text color", () => {
    render(<RefMarker number={1} description="Test" />);
    const text = screen.getByText("1");
    expect(text.style.color).toBe("var(--color-amber)");
  });
});
