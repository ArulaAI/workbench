import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ExplorerPanel } from "@/components/define/explorer-panel";
import type { DefineFeature, DefectData, DefineAggregates } from "@/lib/graphql/queries/define";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

const baseSpec = {
  exists: false,
  path: null,
  auditStatus: "clean",
  warningCount: 0,
  warnings: [],
};

const baseSpecified = {
  productSpec: { ...baseSpec },
  technicalSpec: { ...baseSpec },
  designSpec: { ...baseSpec },
  openQuestions: 0,
  sizingEstimate: null,
};

const baseBuilt = {
  coveragePct: null,
  criteriaPassed: null,
  criteriaTotal: null,
  guardianVerdict: null,
  taskProgress: null,
  tasksDone: null,
  tasksTotal: null,
  blockedCount: 0,
  completedAt: null,
};

const baseGap = {
  escalationCount: 0,
  escalations: [],
  unverifiableCount: 0,
  reworkCount: 0,
};

const baseAggregates: DefineAggregates = {
  designSpecCount: 0,
  featureCount: 2,
  auditWarningCount: 0,
  openQuestionCount: 0,
  escalationCount: 0,
  completedCount: 1,
  executingCount: 0,
  unplannedCount: 1,
};

const features: DefineFeature[] = [
  {
    name: "Auth feature",
    state: "completed",
    specified: {
      ...baseSpecified,
      productSpec: { ...baseSpec, exists: true, path: "/specs/auth/product.md" },
      designSpec: { ...baseSpec, exists: true, path: "/specs/auth/design.md" },
    },
    built: baseBuilt,
    gap: baseGap,
  },
  {
    name: "Dashboard feature",
    state: "unplanned",
    specified: baseSpecified,
    built: baseBuilt,
    gap: baseGap,
  },
];

const defects: DefectData[] = [
  { name: "Login crash", severity: "P0", status: "open", description: "Crash on login", impact: null, filedAt: null },
  { name: "Slow render", severity: "P2", status: "open", description: "Slow", impact: null, filedAt: null },
];

const defaultProps = {
  open: true,
  onClose: vi.fn(),
  features,
  defects,
  aggregates: baseAggregates,
};

describe("ExplorerPanel", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  describe("accessibility", () => {
    it("has role='dialog' with aria-modal", () => {
      render(<ExplorerPanel {...defaultProps} />);
      const dialog = screen.getByRole("dialog");
      expect(dialog).toHaveAttribute("aria-modal", "true");
      expect(dialog).toHaveAttribute("aria-label", "Document explorer");
    });
  });

  describe("header", () => {
    it("shows project name and branch", () => {
      render(<ExplorerPanel {...defaultProps} projectName="myproject" branch="main" />);
      expect(screen.getByText("myproject")).toBeInTheDocument();
      expect(screen.getByText("main")).toBeInTheDocument();
    });

    it("renders close button", () => {
      render(<ExplorerPanel {...defaultProps} />);
      expect(screen.getByRole("button", { name: "Close document explorer" })).toBeInTheDocument();
    });

    it("calls onClose when close button clicked", () => {
      const onClose = vi.fn();
      render(<ExplorerPanel {...defaultProps} onClose={onClose} />);
      fireEvent.click(screen.getByRole("button", { name: "Close document explorer" }));
      expect(onClose).toHaveBeenCalledOnce();
    });
  });

  describe("features section", () => {
    it("renders feature names", () => {
      render(<ExplorerPanel {...defaultProps} />);
      expect(screen.getByText("Auth feature")).toBeInTheDocument();
      expect(screen.getByText("Dashboard feature")).toBeInTheDocument();
    });

    it("shows checkmark for complete features with all specs", () => {
      const completeFeature: DefineFeature = {
        name: "Complete feature",
        state: "completed",
        specified: {
          productSpec: { ...baseSpec, exists: true },
          technicalSpec: { ...baseSpec, exists: true },
          designSpec: { ...baseSpec, exists: true },
          openQuestions: 0,
          sizingEstimate: null,
        },
        built: baseBuilt,
        gap: baseGap,
      };
      render(<ExplorerPanel {...defaultProps} features={[completeFeature]} />);
      expect(screen.getByText("Complete feature")).toBeInTheDocument();
    });

    it("shows empty state when no features", () => {
      render(<ExplorerPanel {...defaultProps} features={[]} />);
      expect(screen.getByText("No features")).toBeInTheDocument();
    });
  });

  describe("defects section", () => {
    it("renders defect names with severity badges", () => {
      render(<ExplorerPanel {...defaultProps} />);
      expect(screen.getByText("Login crash")).toBeInTheDocument();
      expect(screen.getByText("P0")).toBeInTheDocument();
      expect(screen.getByText("Slow render")).toBeInTheDocument();
    });

    it("shows section label with count", () => {
      render(<ExplorerPanel {...defaultProps} />);
      expect(screen.getByText("DEFECTS · 2")).toBeInTheDocument();
    });
  });

  describe("search", () => {
    it("filters features by name", () => {
      render(<ExplorerPanel {...defaultProps} />);
      const input = screen.getByPlaceholderText("Search features, defects…");
      fireEvent.change(input, { target: { value: "Auth" } });
      expect(screen.getByText("Auth feature")).toBeInTheDocument();
      expect(screen.queryByText("Dashboard feature")).not.toBeInTheDocument();
    });

    it("filters defects by name", () => {
      render(<ExplorerPanel {...defaultProps} />);
      const input = screen.getByPlaceholderText("Search features, defects…");
      fireEvent.change(input, { target: { value: "Login" } });
      expect(screen.getByText("Login crash")).toBeInTheDocument();
      expect(screen.queryByText("Slow render")).not.toBeInTheDocument();
    });

    it("shows no matches message when search has no results", () => {
      render(<ExplorerPanel {...defaultProps} />);
      const input = screen.getByPlaceholderText("Search features, defects…");
      fireEvent.change(input, { target: { value: "nonexistent" } });
      expect(screen.getByText("No matches")).toBeInTheDocument();
    });
  });

  describe("keyboard", () => {
    it("calls onClose on Escape when open", () => {
      const onClose = vi.fn();
      render(<ExplorerPanel {...defaultProps} onClose={onClose} />);
      fireEvent.keyDown(document, { key: "Escape" });
      expect(onClose).toHaveBeenCalledOnce();
    });

    it("does not call onClose on Escape when closed", () => {
      const onClose = vi.fn();
      render(<ExplorerPanel {...defaultProps} open={false} onClose={onClose} />);
      fireEvent.keyDown(document, { key: "Escape" });
      expect(onClose).not.toHaveBeenCalled();
    });
  });

  describe("animation", () => {
    it("applies transform transition when prefersReducedMotion is false", () => {
      const { container } = render(<ExplorerPanel {...defaultProps} prefersReducedMotion={false} />);
      const panel = container.firstChild as HTMLElement;
      expect(panel.style.transition).toContain("transform");
    });

    it("applies no transition when prefersReducedMotion is true", () => {
      const { container } = render(<ExplorerPanel {...defaultProps} prefersReducedMotion={true} />);
      const panel = container.firstChild as HTMLElement;
      expect(panel.style.transition).toBe("");
    });
  });

  describe("portfolio audit", () => {
    it("renders audit section", () => {
      render(<ExplorerPanel {...defaultProps} />);
      expect(screen.getByText("PORTFOLIO AUDIT")).toBeInTheDocument();
    });

    it("shows design spec count", () => {
      render(<ExplorerPanel {...defaultProps} aggregates={{ ...baseAggregates, designSpecCount: 2, featureCount: 5 }} />);
      expect(screen.getByText("2 of 5 design specs")).toBeInTheDocument();
    });
  });
});
