import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { DefinePanel } from "@/components/landing/DefinePanel";
import type { DefinePanel as DefinePanelData } from "@/lib/graphql/queries/landing";

const baseDefine: DefinePanelData = {
  visionStatus: "defined",
  draftSpecs: [],
  defects: [],
  defectCount: 0,
};

const mockDefineData: DefinePanelData = {
  visionStatus: "defined",
  draftSpecs: [
    { name: "Auth spec", specTypes: ["product", "technical"], status: "unplanned" },
    { name: "UI spec", specTypes: ["design"], status: "writing" },
    { name: "API spec", specTypes: ["product", "technical", "design"], status: "unplanned" },
  ],
  defects: [
    { severity: "P0", name: "Crash on login" },
    { severity: "P2", name: "Slow dashboard" },
    { severity: "P3", name: "Minor typo" },
  ],
  defectCount: 3,
};

const mockEmptyData: DefinePanelData = {
  visionStatus: "defined",
  draftSpecs: [],
  defects: [],
  defectCount: 0,
};

const mockMissingVision: DefinePanelData = {
  visionStatus: "missing",
  draftSpecs: [{ name: "Onboarding spec", specTypes: ["product"], status: "unplanned" }],
  defects: [],
  defectCount: 0,
};

const mockOverflow: DefinePanelData = {
  visionStatus: "defined",
  draftSpecs: Array.from({ length: 7 }, (_, i) => ({
    name: `Overflow spec ${i + 1}`,
    specTypes: ["product"],
    status: "unplanned",
  })),
  defects: Array.from({ length: 6 }, (_, i) => ({
    severity: "P1",
    name: `Overflow defect ${i + 1}`,
  })),
  defectCount: 6,
};

describe("DefinePanel", () => {
  describe("vision warning", () => {
    it("renders warning banner when visionStatus is 'missing'", () => {
      render(<DefinePanel define={mockMissingVision} />);
      expect(screen.getByText("Product vision missing")).toBeInTheDocument();
    });

    it("does not render warning when visionStatus is 'defined'", () => {
      render(<DefinePanel define={mockDefineData} />);
      expect(screen.queryByText("Product vision missing")).not.toBeInTheDocument();
    });

    it("does not render warning when visionStatus is 'placeholder'", () => {
      render(<DefinePanel define={{ ...baseDefine, visionStatus: "placeholder" }} />);
      expect(screen.queryByText("Product vision missing")).not.toBeInTheDocument();
    });

    it("warning contains 'Product vision missing' text", () => {
      render(<DefinePanel define={{ ...baseDefine, visionStatus: "missing" }} />);
      expect(screen.getByText("Product vision missing")).toBeInTheDocument();
    });

    it("warning contains 'overview.md' code reference", () => {
      render(<DefinePanel define={{ ...baseDefine, visionStatus: "missing" }} />);
      expect(screen.getByText("overview.md")).toBeInTheDocument();
    });
  });

  describe("draft specs", () => {
    it("renders spec names from draftSpecs array", () => {
      render(<DefinePanel define={mockDefineData} />);
      expect(screen.getByText("Auth spec")).toBeInTheDocument();
      expect(screen.getByText("UI spec")).toBeInTheDocument();
      expect(screen.getByText("API spec")).toBeInTheDocument();
    });

    it("renders all three type pills per spec", () => {
      const define: DefinePanelData = {
        ...baseDefine,
        draftSpecs: [{ name: "Test spec", specTypes: ["product"], status: "unplanned" }],
      };
      render(<DefinePanel define={define} />);
      expect(screen.getByText("Product")).toBeInTheDocument();
      expect(screen.getByText("Technical")).toBeInTheDocument();
      expect(screen.getByText("Design")).toBeInTheDocument();
    });

    it("present spec types show full opacity; missing types show opacity 0.35", () => {
      const define: DefinePanelData = {
        ...baseDefine,
        draftSpecs: [{ name: "Test spec", specTypes: ["product"], status: "unplanned" }],
      };
      render(<DefinePanel define={define} />);
      expect(screen.getByText("Product")).toHaveStyle("opacity: 1");
      expect(screen.getByText("Technical")).toHaveStyle("opacity: 0.35");
      expect(screen.getByText("Design")).toHaveStyle("opacity: 0.35");
    });

    it("renders 'unplanned' status badge", () => {
      const define: DefinePanelData = {
        ...baseDefine,
        draftSpecs: [{ name: "Test spec", specTypes: ["product"], status: "unplanned" }],
      };
      render(<DefinePanel define={define} />);
      expect(screen.getByText("unplanned")).toBeInTheDocument();
    });

    it("renders 'writing' status badge", () => {
      const define: DefinePanelData = {
        ...baseDefine,
        draftSpecs: [{ name: "Test spec", specTypes: ["design"], status: "writing" }],
      };
      render(<DefinePanel define={define} />);
      expect(screen.getByText("writing")).toBeInTheDocument();
    });

    it("section label shows correct count", () => {
      render(<DefinePanel define={mockDefineData} />);
      expect(screen.getByText("Specs · 3")).toBeInTheDocument();
    });
  });

  describe("defects", () => {
    it("renders defect names and severity badges", () => {
      render(<DefinePanel define={mockDefineData} />);
      expect(screen.getByText("P0")).toBeInTheDocument();
      expect(screen.getByText("Crash on login")).toBeInTheDocument();
      expect(screen.getByText("P2")).toBeInTheDocument();
      expect(screen.getByText("Slow dashboard")).toBeInTheDocument();
    });

    it("P3 defect row renders at reduced opacity", () => {
      render(<DefinePanel define={mockDefineData} />);
      const p3Row = screen.getByText("Minor typo").parentElement;
      expect(p3Row).toHaveStyle("opacity: 0.35");
    });

    it("defect section hidden when defectCount is 0", () => {
      render(<DefinePanel define={mockEmptyData} />);
      expect(screen.queryByText(/Defects/)).not.toBeInTheDocument();
    });
  });

  describe("overflow", () => {
    it("only 5 specs visible when 7 provided, ViewAllLink shows 'View all 7'", () => {
      render(<DefinePanel define={mockOverflow} />);
      expect(screen.getByText("Overflow spec 1")).toBeInTheDocument();
      expect(screen.getByText("Overflow spec 5")).toBeInTheDocument();
      expect(screen.queryByText("Overflow spec 6")).not.toBeInTheDocument();
      expect(screen.queryByText("Overflow spec 7")).not.toBeInTheDocument();
      expect(screen.getByText("View all 7")).toBeInTheDocument();
    });

    it("only 5 defects visible when 6 provided, ViewAllLink shows 'View all 6'", () => {
      render(<DefinePanel define={mockOverflow} />);
      expect(screen.getByText("Overflow defect 1")).toBeInTheDocument();
      expect(screen.getByText("Overflow defect 5")).toBeInTheDocument();
      expect(screen.queryByText("Overflow defect 6")).not.toBeInTheDocument();
      expect(screen.getByText("View all 6")).toBeInTheDocument();
    });
  });

  describe("empty state", () => {
    it("renders 'Nothing to review.' with empty data", () => {
      render(<DefinePanel define={mockEmptyData} />);
      expect(screen.getByText("Nothing to review.")).toBeInTheDocument();
    });
  });

  describe("navigation", () => {
    it("SurfaceLink renders with href '/spec-alignment'", () => {
      render(<DefinePanel define={baseDefine} />);
      const link = screen.getByRole("link", { name: /Open Define Surface/i });
      expect(link).toHaveAttribute("href", "/spec-alignment");
    });
  });
});
