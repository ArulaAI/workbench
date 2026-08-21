import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { SectionDivider } from "@/components/define/section-divider";

describe("SectionDivider", () => {
  it("renders the defect count", () => {
    render(<SectionDivider count={5} />);
    expect(screen.getByText(/5/)).toBeInTheDocument();
  });

  it("renders the Defects label", () => {
    render(<SectionDivider count={3} />);
    expect(screen.getByText(/Defects/)).toBeInTheDocument();
  });

  it("renders singular count correctly", () => {
    render(<SectionDivider count={1} />);
    expect(screen.getByText(/1/)).toBeInTheDocument();
  });

  it("renders zero count", () => {
    render(<SectionDivider count={0} />);
    expect(screen.getByText(/0/)).toBeInTheDocument();
  });
});
