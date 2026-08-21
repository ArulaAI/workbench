import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type { SpecAlignmentView } from "@/lib/graphql/queries/spec-alignment";

vi.mock("urql", () => ({
  gql: (strings: TemplateStringsArray) => strings.raw.join(""),
  useQuery: vi.fn(),
}));

vi.mock("@/components/shared/progress-bar", () => ({
  ProgressBar: () => <div data-testid="progress-bar" />,
}));

vi.mock("@/components/shared/loading-skeleton", () => ({
  CardSkeleton: () => <div data-testid="card-skeleton" />,
}));

import { useQuery } from "urql";
import SpecAlignmentPage from "./page";

const mockedUseQuery = vi.mocked(useQuery);

/* ── Claim fixtures ──────────────────────────────────────────────── */

const confirmedClaim = {
  source: { specFile: "specs/product/feature.md", section: "Core Features", line: 10 },
  claimType: "behavior",
  claimText: "Users can view spec coverage",
  entity: "spec-alignment",
  status: "confirmed",
  evidence: "app/spec-alignment/page.tsx:42",
  divergence: null,
};

const missingClaim = {
  source: { specFile: "specs/product/feature.md", section: "Core Features", line: 20 },
  claimType: "behavior",
  claimText: "Missing claim example",
  entity: "spec-alignment",
  status: "missing",
  evidence: null,
  divergence: null,
};

const unverifiableClaim = {
  source: { specFile: "specs/product/feature.md", section: "Core Features", line: 30 },
  claimType: "behavior",
  claimText: "Cannot verify this claim",
  entity: "spec-alignment",
  status: "unverifiable",
  evidence: null,
  divergence: null,
};

const divergentClaim = {
  source: { specFile: "specs/product/feature.md", section: "Core Features", line: 40 },
  claimType: "behavior",
  claimText: "Implementation differs from spec",
  entity: "spec-alignment",
  status: "divergent",
  evidence: null,
  divergence: "The implementation uses a different algorithm",
};

/* ── View fixtures ───────────────────────────────────────────────── */

const mockAlignmentData: SpecAlignmentView = {
  totalClaims: 8,
  totalConfirmed: 5,
  totalMissing: 2,
  totalUnverifiable: 1,
  overallCoveragePct: 65,
  specs: [
    {
      specFile: "specs/product/feature.md",
      totalClaims: 4,
      confirmed: 3,
      coveragePct: 75,
      sections: [
        {
          section: "Core Features",
          claimCount: 2,
          confirmed: 1,
          missing: 1,
          unverifiable: 0,
          coveragePct: 50,
          claims: [confirmedClaim, missingClaim],
        },
        {
          section: "Edge Cases",
          claimCount: 2,
          confirmed: 2,
          missing: 0,
          unverifiable: 0,
          coveragePct: 100,
          claims: [
            confirmedClaim,
            { ...confirmedClaim, claimText: "Edge case handled", source: { ...confirmedClaim.source, section: "Edge Cases", line: 60 } },
          ],
        },
      ],
    },
    {
      specFile: "specs/tech/architecture.md",
      totalClaims: 4,
      confirmed: 2,
      coveragePct: 50,
      sections: [
        {
          section: "Data Layer",
          claimCount: 2,
          confirmed: 1,
          missing: 1,
          unverifiable: 0,
          coveragePct: 50,
          claims: [
            { ...confirmedClaim, source: { specFile: "specs/tech/architecture.md", section: "Data Layer", line: 10 } },
            { ...missingClaim, source: { specFile: "specs/tech/architecture.md", section: "Data Layer", line: 20 } },
          ],
        },
        {
          section: "API Design",
          claimCount: 2,
          confirmed: 1,
          missing: 0,
          unverifiable: 1,
          coveragePct: 50,
          claims: [
            { ...confirmedClaim, source: { specFile: "specs/tech/architecture.md", section: "API Design", line: 30 } },
            { ...unverifiableClaim, source: { specFile: "specs/tech/architecture.md", section: "API Design", line: 40 } },
          ],
        },
      ],
    },
  ],
};

const mockEmptyData: SpecAlignmentView = {
  totalClaims: 0,
  totalConfirmed: 0,
  totalMissing: 0,
  totalUnverifiable: 0,
  overallCoveragePct: 0,
  specs: [],
};

const mockHighCoverage: SpecAlignmentView = {
  ...mockAlignmentData,
  overallCoveragePct: 85,
  specs: [],
};

const mockLowCoverage: SpecAlignmentView = {
  ...mockAlignmentData,
  overallCoveragePct: 40,
  specs: [],
};

/* ── Single-spec fixture for section/claim tests ─────────────────── */

const singleSpecFixture: SpecAlignmentView = {
  totalClaims: 10,
  totalConfirmed: 8,
  totalMissing: 1,
  totalUnverifiable: 1,
  overallCoveragePct: 82,
  specs: [
    {
      specFile: "specs/product/feature.md",
      totalClaims: 10,
      confirmed: 8,
      coveragePct: 90,
      sections: [
        {
          section: "Core Features",
          claimCount: 4,
          confirmed: 3,
          missing: 1,
          unverifiable: 0,
          coveragePct: 75,
          claims: [confirmedClaim, missingClaim, unverifiableClaim, divergentClaim],
        },
      ],
    },
  ],
};

/* ── Helpers ─────────────────────────────────────────────────────── */

function setupQuery(overrides: {
  fetching?: boolean;
  error?: Error | null;
  data?: { specAlignment: SpecAlignmentView | null } | null;
} = {}) {
  const { fetching = false, error = null, data = { specAlignment: singleSpecFixture } } = overrides;
  mockedUseQuery.mockReturnValue([
    { data, fetching, error, stale: false, extensions: undefined },
    vi.fn(),
  ] as unknown as ReturnType<typeof useQuery>);
}

// Claim badges use "type-badge" class; summary bar labels use "type-kpi-label".
// This helper avoids false matches when both exist in the DOM.
function getClaimBadge(text: string): HTMLElement {
  const elements = screen.queryAllByText(text);
  const badge = elements.find((el) => el.classList.contains("type-badge"));
  if (!badge) throw new Error(`No claim badge found with text: ${text}`);
  return badge;
}

const mockWriteText = vi.fn();

/* ── Tests ───────────────────────────────────────────────────────── */

describe("SpecAlignmentPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockWriteText.mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: mockWriteText },
      writable: true,
      configurable: true,
    });
  });

  describe("loading state", () => {
    it("renders four CardSkeleton components while fetching", () => {
      setupQuery({ fetching: true, data: null });
      render(<SpecAlignmentPage />);
      expect(screen.getAllByTestId("card-skeleton")).toHaveLength(4);
    });
  });

  describe("error state", () => {
    it("renders error message when query fails", () => {
      setupQuery({ error: new Error("GraphQL error"), data: null });
      render(<SpecAlignmentPage />);
      expect(screen.getByText(/Error: GraphQL error/)).toBeInTheDocument();
    });
  });

  describe("empty state", () => {
    it("shows speed plan code tag when specAlignment is null", () => {
      setupQuery({ data: { specAlignment: null } });
      render(<SpecAlignmentPage />);
      expect(screen.getByText("speed plan")).toBeInTheDocument();
    });

    it("renders the explanatory message alongside the code tag", () => {
      setupQuery({ data: null });
      render(<SpecAlignmentPage />);
      expect(screen.getByText(/No spec alignment data found/)).toBeInTheDocument();
    });
  });

  describe("summary bar", () => {
    it("renders stat values matching fixture data", () => {
      setupQuery();
      render(<SpecAlignmentPage />);
      expect(screen.getByText("82.0%")).toBeInTheDocument();
      expect(screen.getByText("10")).toBeInTheDocument();
      expect(screen.getByText("8")).toBeInTheDocument();
      expect(screen.getByText("1")).toBeInTheDocument();
    });

    it("renders ProgressBar in summary", () => {
      setupQuery();
      render(<SpecAlignmentPage />);
      expect(screen.getAllByTestId("progress-bar").length).toBeGreaterThanOrEqual(1);
    });
  });

  describe("coverage color thresholds", () => {
    it("applies emerald color for coverage >= 80%", () => {
      setupQuery({ data: { specAlignment: mockHighCoverage } });
      render(<SpecAlignmentPage />);
      expect(screen.getByText("85.0%").style.color).toBe("var(--color-emerald)");
    });

    it("applies amber color for coverage between 50% and 79%", () => {
      setupQuery({ data: { specAlignment: { ...mockAlignmentData, overallCoveragePct: 65, specs: [] } } });
      render(<SpecAlignmentPage />);
      expect(screen.getByText("65.0%").style.color).toBe("var(--color-amber)");
    });

    it("applies red color for coverage below 50%", () => {
      setupQuery({ data: { specAlignment: mockLowCoverage } });
      render(<SpecAlignmentPage />);
      expect(screen.getByText("40.0%").style.color).toBe("var(--color-red)");
    });
  });

  describe("spec cards", () => {
    it("renders correct number of spec cards for mockAlignmentData", () => {
      setupQuery({ data: { specAlignment: mockAlignmentData } });
      render(<SpecAlignmentPage />);
      expect(screen.getByText("feature.md")).toBeInTheDocument();
      expect(screen.getByText("architecture.md")).toBeInTheDocument();
    });

    it("displays last path segment as filename", () => {
      setupQuery();
      render(<SpecAlignmentPage />);
      expect(screen.getByText("feature.md")).toBeInTheDocument();
    });

    it("shows coverage percentage and claim fraction", () => {
      setupQuery();
      render(<SpecAlignmentPage />);
      expect(screen.getByText("90.0%")).toBeInTheDocument();
      expect(screen.getByText("8/10 claims")).toBeInTheDocument();
    });
  });

  describe("section expand/collapse", () => {
    it("hides claims initially and shows them after clicking the section button", () => {
      setupQuery();
      render(<SpecAlignmentPage />);

      expect(screen.queryByText("Users can view spec coverage")).not.toBeInTheDocument();

      const sectionButton = screen.getByText("Core Features").closest("button")!;
      fireEvent.click(sectionButton);

      expect(screen.getByText("Users can view spec coverage")).toBeInTheDocument();
    });

    it("collapses section again on second click", () => {
      setupQuery();
      render(<SpecAlignmentPage />);

      const sectionButton = screen.getByText("Core Features").closest("button")!;
      fireEvent.click(sectionButton);
      expect(screen.getByText("Users can view spec coverage")).toBeInTheDocument();

      fireEvent.click(sectionButton);
      expect(screen.queryByText("Users can view spec coverage")).not.toBeInTheDocument();
    });
  });

  describe("claim status badges", () => {
    beforeEach(() => {
      setupQuery();
      render(<SpecAlignmentPage />);
      const sectionButton = screen.getByText("Core Features").closest("button")!;
      fireEvent.click(sectionButton);
    });

    it("confirmed badge renders with emerald color", () => {
      expect(getClaimBadge("Confirmed").style.color).toBe("var(--color-emerald)");
    });

    it("missing badge renders with red color", () => {
      expect(getClaimBadge("Missing").style.color).toBe("var(--color-red)");
    });

    it("unverifiable badge renders with tertiary color", () => {
      expect(getClaimBadge("Unverifiable").style.color).toBe("var(--color-text-tertiary)");
    });

    it("divergent badge renders with amber color", () => {
      expect(getClaimBadge("Divergent").style.color).toBe("var(--color-amber)");
    });
  });

  describe("evidence copy button", () => {
    it("calls clipboard writeText with the evidence string on click", () => {
      setupQuery();
      render(<SpecAlignmentPage />);

      const sectionButton = screen.getByText("Core Features").closest("button")!;
      fireEvent.click(sectionButton);

      const copyButton = screen.getByText("app/spec-alignment/page.tsx:42").closest("button")!;
      fireEvent.click(copyButton);

      expect(mockWriteText).toHaveBeenCalledWith("app/spec-alignment/page.tsx:42");
    });

    it("does not render evidence button when evidence is null", () => {
      setupQuery();
      render(<SpecAlignmentPage />);

      const sectionButton = screen.getByText("Core Features").closest("button")!;
      fireEvent.click(sectionButton);

      // Only the confirmed claim has evidence; three other claims have evidence: null
      const evidenceLinks = screen.queryAllByText("app/spec-alignment/page.tsx:42");
      expect(evidenceLinks).toHaveLength(1);
    });
  });

  describe("divergent claim text", () => {
    it("renders divergence description with the text-amber CSS class", () => {
      setupQuery();
      render(<SpecAlignmentPage />);

      const sectionButton = screen.getByText("Core Features").closest("button")!;
      fireEvent.click(sectionButton);

      const divergenceEl = screen.getByText(/The implementation uses a different algorithm/);
      expect(divergenceEl).toHaveClass("text-amber");
    });
  });
});
