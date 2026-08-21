import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { JudgePanel } from "@/components/landing/JudgePanel";
import type { JudgePanel as JudgePanelData } from "@/lib/graphql/queries/landing";

const mockPush = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));

const basePendingReview = {
  feature: "auth-v2",
  completedAt: "2026-03-15T10:00:00Z",
  coveragePct: 82,
  criteriaPassed: 9,
  criteriaTotal: 11,
  guardianVerdict: "pass",
  decisionsNeeded: 2,
  summary: null,
};

const baseJudge: JudgePanelData = {
  pendingReview: basePendingReview,
  lastCompleted: null,
};

beforeEach(() => {
  mockPush.mockClear();
});

describe("JudgePanel", () => {
  describe("HeroMetrics", () => {
    it("renders coverage percentage", () => {
      render(<JudgePanel judge={baseJudge} narrative={null} />);
      expect(screen.getByText("82%")).toBeInTheDocument();
    });

    it("renders criteria passed/total", () => {
      render(<JudgePanel judge={baseJudge} narrative={null} />);
      expect(screen.getByText("9/11")).toBeInTheDocument();
    });

    it("renders guardian verdict", () => {
      render(<JudgePanel judge={baseJudge} narrative={null} />);
      expect(screen.getByText("pass")).toBeInTheDocument();
    });

    it("renders decisions count", () => {
      render(<JudgePanel judge={baseJudge} narrative={null} />);
      // The hero metric cell and the DecisionCount label both reference decisionsNeeded
      const twos = screen.getAllByText("2");
      expect(twos.length).toBeGreaterThan(0);
    });

    it("renders em-dash for null guardian verdict", () => {
      const judge: JudgePanelData = {
        ...baseJudge,
        pendingReview: { ...basePendingReview, guardianVerdict: null },
      };
      render(<JudgePanel judge={judge} narrative={null} />);
      expect(screen.getByText("—")).toBeInTheDocument();
    });

    it("applies accent color only to coverage metric", () => {
      render(<JudgePanel judge={baseJudge} narrative={null} />);
      const coverageValue = screen.getByText("82%");
      expect(coverageValue).toHaveStyle({ color: "var(--color-accent)" });

      const criteriaValue = screen.getByText("9/11");
      expect(criteriaValue).toHaveStyle({ color: "var(--color-text)" });
    });
  });

  describe("ReviewSummary", () => {
    it("renders narrative text when provided", () => {
      render(<JudgePanel judge={baseJudge} narrative="Auth coverage looks solid across happy paths." />);
      expect(screen.getByText("Auth coverage looks solid across happy paths.")).toBeInTheDocument();
    });

    it("renders bullet fallback when narrative is null", () => {
      render(<JudgePanel judge={baseJudge} narrative={null} />);
      expect(screen.getByText("82% of criteria covered")).toBeInTheDocument();
      expect(screen.getByText("9 of 11 criteria passed")).toBeInTheDocument();
    });

    it("includes guardian verdict in bullet fallback", () => {
      render(<JudgePanel judge={baseJudge} narrative={null} />);
      expect(screen.getByText("Guardian: pass")).toBeInTheDocument();
    });

    it("includes decisions needed in bullet fallback when > 0", () => {
      render(<JudgePanel judge={baseJudge} narrative={null} />);
      const bullets = screen.getAllByRole("listitem");
      const decisionBullet = bullets.find((el) => el.textContent === "2 decisions needed");
      expect(decisionBullet).toBeInTheDocument();
    });

    it("omits decisions bullet when decisionsNeeded is 0", () => {
      const judge: JudgePanelData = {
        ...baseJudge,
        pendingReview: { ...basePendingReview, decisionsNeeded: 0 },
      };
      render(<JudgePanel judge={judge} narrative={null} />);
      const bullets = screen.queryAllByRole("listitem");
      const decisionBullet = bullets.find((el) => /decisions needed/.test(el.textContent || ""));
      expect(decisionBullet).toBeUndefined();
    });
  });

  describe("DecisionCount", () => {
    it("shows amber badge when decisionsNeeded > 0", () => {
      render(<JudgePanel judge={baseJudge} narrative={null} />);
      const elements = screen.getAllByText("2 decisions needed");
      const badge = elements.find((el) => el.tagName === "SPAN");
      expect(badge).toHaveStyle({ color: "var(--color-amber)" });
    });

    it("shows calm secondary label when decisionsNeeded is 0", () => {
      const judge: JudgePanelData = {
        ...baseJudge,
        pendingReview: { ...basePendingReview, decisionsNeeded: 0 },
      };
      render(<JudgePanel judge={judge} narrative={null} />);
      const label = screen.getByText("No decisions needed");
      expect(label).toHaveStyle({ color: "var(--color-text-secondary)" });
    });

    it("uses singular form for 1 decision", () => {
      const judge: JudgePanelData = {
        ...baseJudge,
        pendingReview: { ...basePendingReview, decisionsNeeded: 1 },
      };
      render(<JudgePanel judge={judge} narrative={null} />);
      const elements = screen.getAllByText("1 decision needed");
      expect(elements.length).toBeGreaterThan(0);
    });
  });

  describe("CTA button", () => {
    it("renders Review & decide button", () => {
      render(<JudgePanel judge={baseJudge} narrative={null} />);
      expect(screen.getByRole("button", { name: /review & decide/i })).toBeInTheDocument();
    });

    it("navigates to /outcome-review with feature param on click", () => {
      render(<JudgePanel judge={baseJudge} narrative={null} />);
      fireEvent.click(screen.getByRole("button", { name: /review & decide/i }));
      expect(mockPush).toHaveBeenCalledWith("/outcome-review?feature=auth-v2");
    });
  });

  describe("Empty state", () => {
    it("renders 'No reviews pending' when pendingReview is null", () => {
      const judge: JudgePanelData = { pendingReview: null, lastCompleted: null };
      render(<JudgePanel judge={judge} narrative={null} />);
      expect(screen.getByText("No reviews pending")).toBeInTheDocument();
    });

    it("does not render CTA button in empty state", () => {
      const judge: JudgePanelData = { pendingReview: null, lastCompleted: null };
      render(<JudgePanel judge={judge} narrative={null} />);
      expect(screen.queryByRole("button", { name: /review & decide/i })).not.toBeInTheDocument();
    });

    it("shows lastCompleted summary in empty state when available", () => {
      const judge: JudgePanelData = {
        pendingReview: null,
        lastCompleted: { feature: "payments-v1", verdict: "pass", coveragePct: 91 },
      };
      render(<JudgePanel judge={judge} narrative={null} />);
      expect(screen.getByText(/payments-v1/)).toBeInTheDocument();
      expect(screen.getByText(/91%/)).toBeInTheDocument();
    });

    it("does not show lastCompleted section when lastCompleted is null", () => {
      const judge: JudgePanelData = { pendingReview: null, lastCompleted: null };
      render(<JudgePanel judge={judge} narrative={null} />);
      expect(screen.queryByText(/Last completed/i)).not.toBeInTheDocument();
    });
  });

  describe("Layout", () => {
    it("applies .surface class to the card container", () => {
      const { container } = render(<JudgePanel judge={baseJudge} narrative={null} />);
      expect(container.firstChild).toHaveClass("surface");
    });

    it("applies .surface class in empty state", () => {
      const judge: JudgePanelData = { pendingReview: null, lastCompleted: null };
      const { container } = render(<JudgePanel judge={judge} narrative={null} />);
      expect(container.firstChild).toHaveClass("surface");
    });
  });
});
