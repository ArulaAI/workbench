import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { LearnPanel } from "@/components/landing/LearnPanel";
import type { LearnPanel as LearnPanelData } from "@/lib/graphql/queries/landing";

const baseLearn: LearnPanelData = {
  coverageTrend: [],
  insights: [],
  escalationTrend: [],
};

describe("LearnPanel", () => {
  it("applies .surface class to the card container", () => {
    const { container } = render(<LearnPanel {...baseLearn} />);
    expect(container.firstChild).toHaveClass("surface");
  });

  it("shows empty state when all arrays are empty", () => {
    render(<LearnPanel {...baseLearn} />);
    expect(screen.getByText("No learning data yet.")).toBeInTheDocument();
  });

  it("hides empty state when any array has data", () => {
    render(
      <LearnPanel
        {...baseLearn}
        insights={[{ type: "good", text: "Coverage improved" }]}
      />
    );
    expect(screen.queryByText("No learning data yet.")).not.toBeInTheDocument();
  });

  it("renders coverage trend rows with feature names and percentages", () => {
    render(
      <LearnPanel
        {...baseLearn}
        coverageTrend={[
          { feature: "Auth", coveragePct: 80 },
          { feature: "Billing", coveragePct: 60 },
        ]}
      />
    );
    expect(screen.getByText("Auth")).toBeInTheDocument();
    expect(screen.getByText("80%")).toBeInTheDocument();
    expect(screen.getByText("Billing")).toBeInTheDocument();
    expect(screen.getByText("60%")).toBeInTheDocument();
  });

  it("sorts coverage trend descending by coveragePct", () => {
    render(
      <LearnPanel
        {...baseLearn}
        coverageTrend={[
          { feature: "Low", coveragePct: 30 },
          { feature: "High", coveragePct: 90 },
          { feature: "Mid", coveragePct: 60 },
        ]}
      />
    );
    const cells = screen.getAllByText(/High|Mid|Low/);
    expect(cells[0].textContent).toBe("High");
    expect(cells[1].textContent).toBe("Mid");
    expect(cells[2].textContent).toBe("Low");
  });

  it("renders insight cards with green dot for good type", () => {
    render(
      <LearnPanel
        {...baseLearn}
        insights={[{ type: "good", text: "Tests improved" }]}
      />
    );
    expect(screen.getByText("Tests improved")).toBeInTheDocument();
    const dot = screen.getByLabelText("good");
    expect(dot).toHaveStyle({ backgroundColor: "var(--color-emerald)" });
  });

  it("renders insight cards with amber dot for warn type", () => {
    render(
      <LearnPanel
        {...baseLearn}
        insights={[{ type: "warn", text: "Flaky tests detected" }]}
      />
    );
    expect(screen.getByText("Flaky tests detected")).toBeInTheDocument();
    const dot = screen.getByLabelText("warning");
    expect(dot).toHaveStyle({ backgroundColor: "var(--color-amber)" });
  });

  it("shows at most 5 insights", () => {
    const manyInsights = Array.from({ length: 7 }, (_, i) => ({
      type: "good",
      text: `Insight ${i + 1}`,
    }));
    render(<LearnPanel {...baseLearn} insights={manyInsights} />);
    expect(screen.queryByText("Insight 6")).not.toBeInTheDocument();
    expect(screen.queryByText("Insight 7")).not.toBeInTheDocument();
    expect(screen.getByText("Insight 5")).toBeInTheDocument();
  });

  it("renders escalation trend with feature names and count badges", () => {
    render(
      <LearnPanel
        {...baseLearn}
        escalationTrend={[
          { feature: "Payments", count: 1 },
          { feature: "Auth", count: 5 },
        ]}
      />
    );
    expect(screen.getByText("Payments")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText("Auth")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
  });

  it("applies amber style to escalation counts >= 3", () => {
    render(
      <LearnPanel
        {...baseLearn}
        escalationTrend={[
          { feature: "High", count: 4 },
          { feature: "Low", count: 1 },
        ]}
      />
    );
    const highBadge = screen.getByText("4");
    const lowBadge = screen.getByText("1");
    expect(highBadge).toHaveStyle({ color: "var(--color-amber)" });
    expect(lowBadge).not.toHaveStyle({ color: "var(--color-amber)" });
  });
});
