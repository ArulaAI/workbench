import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { SpecPill } from "@/components/define/spec-pill";

describe("SpecPill", () => {
  describe("label rendering", () => {
    it("renders Product label", () => {
      render(<SpecPill label="Product" state="present" />);
      expect(screen.getByText("Product")).toBeInTheDocument();
    });

    it("renders Technical label", () => {
      render(<SpecPill label="Technical" state="present" />);
      expect(screen.getByText("Technical")).toBeInTheDocument();
    });

    it("renders Design label", () => {
      render(<SpecPill label="Design" state="present" />);
      expect(screen.getByText("Design")).toBeInTheDocument();
    });
  });

  describe("present state", () => {
    it("uses emerald text color", () => {
      render(<SpecPill label="Product" state="present" />);
      expect(screen.getByText("Product")).toHaveStyle({
        color: "var(--color-emerald)",
      });
    });

    it("uses emerald background", () => {
      render(<SpecPill label="Product" state="present" />);
      expect(screen.getByText("Product")).toHaveStyle({
        background: "rgba(68, 204, 119, 0.06)",
      });
    });
  });

  describe("warning state", () => {
    it("uses amber text color", () => {
      render(<SpecPill label="Technical" state="warning" />);
      expect(screen.getByText("Technical")).toHaveStyle({
        color: "var(--color-amber)",
      });
    });

    it("uses amber background", () => {
      render(<SpecPill label="Technical" state="warning" />);
      expect(screen.getByText("Technical")).toHaveStyle({
        background: "rgba(240, 178, 50, 0.06)",
      });
    });
  });

  describe("missing state", () => {
    it("uses tertiary text color", () => {
      render(<SpecPill label="Design" state="missing" />);
      expect(screen.getByText("Design")).toHaveStyle({
        color: "var(--color-text-tertiary)",
      });
    });

    it("uses card background", () => {
      render(<SpecPill label="Design" state="missing" />);
      expect(screen.getByText("Design")).toHaveStyle({
        background: "var(--color-bg-card)",
      });
    });

    it("uses dashed border style", () => {
      render(<SpecPill label="Design" state="missing" />);
      expect(screen.getByText("Design")).toHaveStyle({
        borderStyle: "dashed",
      });
    });
  });

  describe("typography", () => {
    it("uses monospace font", () => {
      render(<SpecPill label="Product" state="present" />);
      expect(screen.getByText("Product")).toHaveStyle({
        fontFamily: "var(--font-mono)",
      });
    });

    it("uses 9px font size and weight 500", () => {
      render(<SpecPill label="Product" state="present" />);
      expect(screen.getByText("Product")).toHaveStyle({
        fontSize: "9px",
        fontWeight: "500",
      });
    });
  });
});
