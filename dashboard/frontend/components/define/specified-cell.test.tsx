import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { SpecifiedCell } from "@/components/define/specified-cell";

const baseSpecInfo = {
  exists: true,
  path: "/specs/product.md",
  auditStatus: "clean",
  warningCount: 0,
  warnings: [],
};

const baseSpecified = {
  productSpec: { ...baseSpecInfo },
  technicalSpec: { ...baseSpecInfo },
  designSpec: { ...baseSpecInfo },
  openQuestions: 0,
  sizingEstimate: null,
};

describe("SpecifiedCell", () => {
  describe("feature name", () => {
    it("renders the feature name", () => {
      render(
        <SpecifiedCell name="Auth feature" state="executing" specified={baseSpecified} />,
      );
      expect(screen.getByText("Auth feature")).toBeInTheDocument();
    });

    it("truncates names longer than 32 characters with ellipsis", () => {
      const longName = "A very long feature name that exceeds the limit";
      render(<SpecifiedCell name={longName} state="executing" specified={baseSpecified} />);
      expect(screen.getByText("A very long feature name that ex\u2026")).toBeInTheDocument();
    });

    it("does not truncate names of exactly 32 characters", () => {
      const name = "Exactly thirty-two chars long!!!";
      render(<SpecifiedCell name={name} state="executing" specified={baseSpecified} />);
      expect(screen.getByText(name)).toBeInTheDocument();
    });
  });

  describe("StateBadge", () => {
    it("renders COMPLETE badge for complete state", () => {
      render(
        <SpecifiedCell name="Feature" state="complete" specified={baseSpecified} />,
      );
      expect(screen.getByText("COMPLETE")).toBeInTheDocument();
    });

    it("renders EXECUTING badge for executing state", () => {
      render(
        <SpecifiedCell name="Feature" state="executing" specified={baseSpecified} />,
      );
      expect(screen.getByText("EXECUTING")).toBeInTheDocument();
    });

    it("renders WRITING badge for writing state", () => {
      render(
        <SpecifiedCell name="Feature" state="writing" specified={baseSpecified} />,
      );
      expect(screen.getByText("WRITING")).toBeInTheDocument();
    });

    it("renders UNPLANNED badge in compact variant", () => {
      render(
        <SpecifiedCell name="Feature" state="unplanned" specified={baseSpecified} />,
      );
      expect(screen.getByText("UNPLANNED")).toBeInTheDocument();
    });
  });

  describe("spec pills", () => {
    it("renders all three spec pills", () => {
      render(
        <SpecifiedCell name="Feature" state="executing" specified={baseSpecified} />,
      );
      expect(screen.getByText("Product")).toBeInTheDocument();
      expect(screen.getByText("Technical")).toBeInTheDocument();
      expect(screen.getByText("Design")).toBeInTheDocument();
    });

    it("derives missing state when spec does not exist", () => {
      const specified = {
        ...baseSpecified,
        designSpec: { ...baseSpecInfo, exists: false, path: null },
      };
      render(<SpecifiedCell name="Feature" state="executing" specified={specified} />);
      const designPill = screen.getByText("Design");
      expect(designPill).toHaveStyle({ color: "var(--color-text-tertiary)" });
    });

    it("derives warning state when auditStatus is 'warning'", () => {
      const specified = {
        ...baseSpecified,
        productSpec: { ...baseSpecInfo, auditStatus: "warning", warningCount: 1, warnings: ["Missing acceptance criteria"] },
      };
      render(<SpecifiedCell name="Feature" state="executing" specified={specified} />);
      const productPill = screen.getByText("Product");
      expect(productPill).toHaveStyle({ color: "var(--color-amber)" });
    });

    it("derives warning state when auditStatus is 'error'", () => {
      const specified = {
        ...baseSpecified,
        technicalSpec: { ...baseSpecInfo, auditStatus: "error", warningCount: 1, warnings: ["Incomplete spec"] },
      };
      render(<SpecifiedCell name="Feature" state="executing" specified={specified} />);
      const techPill = screen.getByText("Technical");
      expect(techPill).toHaveStyle({ color: "var(--color-amber)" });
    });

    it("derives present state when spec exists with no audit issues", () => {
      render(
        <SpecifiedCell name="Feature" state="executing" specified={baseSpecified} />,
      );
      const productPill = screen.getByText("Product");
      expect(productPill).toHaveStyle({ color: "var(--color-emerald)" });
    });
  });

  describe("audit warnings", () => {
    it("shows warning count when warnings exist", () => {
      const specified = {
        ...baseSpecified,
        productSpec: {
          ...baseSpecInfo,
          auditStatus: "warning",
          warningCount: 2,
          warnings: ["Missing criteria", "No scope defined"],
        },
      };
      render(<SpecifiedCell name="Feature" state="executing" specified={specified} />);
      expect(screen.getByText("2 warnings")).toBeInTheDocument();
    });

    it("shows singular 'warning' for count of 1", () => {
      const specified = {
        ...baseSpecified,
        productSpec: {
          ...baseSpecInfo,
          auditStatus: "warning",
          warningCount: 1,
          warnings: ["Missing criteria"],
        },
      };
      render(<SpecifiedCell name="Feature" state="executing" specified={specified} />);
      expect(screen.getByText("1 warning")).toBeInTheDocument();
    });

    it("shows individual warning text lines", () => {
      const specified = {
        ...baseSpecified,
        productSpec: {
          ...baseSpecInfo,
          auditStatus: "warning",
          warningCount: 1,
          warnings: ["Missing acceptance criteria"],
        },
      };
      render(<SpecifiedCell name="Feature" state="executing" specified={specified} />);
      expect(screen.getByText("Missing acceptance criteria")).toBeInTheDocument();
    });

    it("does not render warning section when no warnings", () => {
      render(
        <SpecifiedCell name="Feature" state="executing" specified={baseSpecified} />,
      );
      expect(screen.queryByText(/warning/)).not.toBeInTheDocument();
    });
  });

  describe("open questions", () => {
    it("shows open question count when present", () => {
      const specified = { ...baseSpecified, openQuestions: 3 };
      render(<SpecifiedCell name="Feature" state="executing" specified={specified} />);
      expect(screen.getByText("3 open questions")).toBeInTheDocument();
    });

    it("uses singular for count of 1", () => {
      const specified = { ...baseSpecified, openQuestions: 1 };
      render(<SpecifiedCell name="Feature" state="executing" specified={specified} />);
      expect(screen.getByText("1 open question")).toBeInTheDocument();
    });

    it("does not render when open questions is 0", () => {
      render(
        <SpecifiedCell name="Feature" state="executing" specified={baseSpecified} />,
      );
      expect(screen.queryByText(/open question/)).not.toBeInTheDocument();
    });
  });

  describe("sizing estimate", () => {
    it("renders sizing estimate when present", () => {
      const specified = { ...baseSpecified, sizingEstimate: 3 };
      render(<SpecifiedCell name="Feature" state="executing" specified={specified} />);
      expect(screen.getByText("3")).toBeInTheDocument();
    });

    it("does not render sizing estimate when null", () => {
      render(
        <SpecifiedCell name="Feature" state="executing" specified={baseSpecified} />,
      );
      expect(screen.queryByText("weeks")).not.toBeInTheDocument();
    });
  });

  describe("compact variant (unplanned)", () => {
    it("renders name and badge in single row without spec pills", () => {
      render(
        <SpecifiedCell name="Unplanned feature" state="unplanned" specified={baseSpecified} />,
      );
      expect(screen.getByText("Unplanned feature")).toBeInTheDocument();
      expect(screen.getByText("UNPLANNED")).toBeInTheDocument();
      expect(screen.queryByText("Product")).not.toBeInTheDocument();
    });

    it("applies compact padding of 10px 20px", () => {
      const { container } = render(
        <SpecifiedCell name="Feature" state="unplanned" specified={baseSpecified} />,
      );
      const cell = container.firstChild as HTMLElement;
      expect(cell).toHaveStyle({ padding: "10px 20px" });
    });
  });

  describe("full variant padding", () => {
    it("applies full padding of 16px 20px for non-unplanned states", () => {
      const { container } = render(
        <SpecifiedCell name="Feature" state="executing" specified={baseSpecified} />,
      );
      const cell = container.firstChild as HTMLElement;
      expect(cell).toHaveStyle({ padding: "16px 20px" });
    });
  });
});
