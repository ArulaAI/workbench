import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { VisionWarning } from "@/components/shared/vision-warning";

describe("VisionWarning", () => {
  it("renders the warning heading", () => {
    render(<VisionWarning />);
    expect(screen.getByText("Product vision missing")).toBeInTheDocument();
  });

  it("renders the overview.md code reference", () => {
    render(<VisionWarning />);
    expect(screen.getByText("overview.md")).toBeInTheDocument();
  });

  it("renders the Create vision CTA", () => {
    render(<VisionWarning />);
    expect(screen.getByText("Create vision")).toBeInTheDocument();
  });

  it("card variant renders without explicit width style", () => {
    const { container } = render(<VisionWarning variant="card" />);
    const wrapper = container.firstChild as HTMLElement;
    expect(wrapper.style.width).toBe("");
  });

  it("full variant renders with width 100%", () => {
    const { container } = render(<VisionWarning variant="full" />);
    const wrapper = container.firstChild as HTMLElement;
    expect(wrapper.style.width).toBe("100%");
  });

  it("defaults to card variant when no variant prop provided", () => {
    const { container } = render(<VisionWarning />);
    const wrapper = container.firstChild as HTMLElement;
    expect(wrapper.style.width).toBe("");
  });
});
