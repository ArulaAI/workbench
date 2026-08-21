import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import type {
  DefinePanel as DefinePanelData,
  JudgePanel as JudgePanelData,
  ExecutePanel as ExecutePanelData,
  LearnPanel as LearnPanelData,
  LandingViewData,
} from "@/lib/graphql/queries/landing";

const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));

vi.mock("urql", () => ({
  useQuery: vi.fn(),
  useMutation: vi.fn(),
  useSubscription: vi.fn(),
  // gql is used at module load time by landing.ts and mission-control.ts
  gql: (strings: TemplateStringsArray) => strings.raw.join(""),
}));

import { EditorialGrid } from "@/components/landing/EditorialGrid";
import { DefinePanel } from "@/components/landing/DefinePanel";
import { JudgePanel } from "@/components/landing/JudgePanel";
import { ExecutePanel } from "@/components/landing/ExecutePanel";
import { LearnPanel } from "@/components/landing/LearnPanel";
import { useQuery, useMutation, useSubscription } from "urql";
import Home from "@/app/page";

const mockedUseQuery = vi.mocked(useQuery);
const mockedUseMutation = vi.mocked(useMutation);
const mockedUseSubscription = vi.mocked(useSubscription);

// --- Fixtures ---

const defineFixture: DefinePanelData = {
  visionStatus: "defined",
  draftSpecs: [
    { name: "auth-spec", specTypes: ["product", "tech"], status: "ready" },
  ],
  defects: [
    { severity: "P0", name: "Login fails on mobile" },
    { severity: "P2", name: "Slow token refresh" },
  ],
  defectCount: 2,
};

const judgeFixture: JudgePanelData = {
  pendingReview: {
    feature: "auth-v2",
    completedAt: "2026-03-15T10:00:00Z",
    coveragePct: 78,
    criteriaPassed: 7,
    criteriaTotal: 10,
    guardianVerdict: "pass",
    decisionsNeeded: 3,
    summary: null,
  },
  lastCompleted: null,
};

const executeFixture: ExecutePanelData = {
  runningFeatures: [
    { name: "auth-v2", progressPct: 65, tasksCompleted: 13, tasksTotal: 20, blockedCount: 0 },
  ],
  escalations: [
    { feature: "auth-v2", taskId: "task-5", taskTitle: "Setup OAuth", question: "Use PKCE?" },
  ],
};

// Coverage trend feature names ("auth", "notifications", "billing") deliberately differ
// from escalation trend features ("payments", "legacy") to avoid getAllByText collisions.
const learnFixture: LearnPanelData = {
  coverageTrend: [
    { feature: "billing", coveragePct: 40 },
    { feature: "auth", coveragePct: 90 },
    { feature: "notifications", coveragePct: 60 },
  ],
  insights: [
    { type: "good", text: "Auth coverage improved" },
    { type: "warn", text: "Billing tests flaky" },
  ],
  escalationTrend: [
    { feature: "payments", count: 2 },
    { feature: "legacy", count: 4 },
  ],
};

const baseLandingView: LandingViewData = {
  landingView: {
    greeting: "Good morning",
    projectName: "speed",
    branch: "main",
    narrative: null,
    define: defineFixture,
    judge: judgeFixture,
    execute: executeFixture,
    learn: learnFixture,
  },
};

function setupUrqlHooks(overrides: {
  fetching?: boolean;
  error?: Error | null;
  data?: LandingViewData | null;
} = {}) {
  const { fetching = false, error = null, data = baseLandingView } = overrides;

  mockedUseQuery.mockReturnValue([
    { data, fetching, error, stale: false, extensions: undefined } as ReturnType<typeof useQuery>[0],
    vi.fn(),
  ] as unknown as ReturnType<typeof useQuery>);

  mockedUseMutation.mockReturnValue([
    { fetching: false, stale: false, error: undefined, extensions: undefined, data: undefined },
    vi.fn(),
  ] as unknown as ReturnType<typeof useMutation>);

  mockedUseSubscription.mockReturnValue([
    { data: null, error: null, fetching: false, stale: false, extensions: undefined } as ReturnType<typeof useSubscription>[0],
    vi.fn(),
  ] as unknown as ReturnType<typeof useSubscription>);
}

const mockOnRespond = vi.fn();

describe("LandingPage components", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockOnRespond.mockResolvedValue(undefined);
  });

  // ---- 1. EditorialGrid grid layout ----

  describe("EditorialGrid grid layout", () => {
    it("sets gridTemplateColumns to 260px 1fr 320px", () => {
      const { container } = render(
        <EditorialGrid
          definePanel={<div>Define</div>}
          judgePanel={<div>Judge</div>}
          executePanel={<div>Execute</div>}
          learnPanel={<div>Learn</div>}
        />
      );
      const grid = container.firstChild as HTMLElement;
      expect(grid.style.gridTemplateColumns).toBe("260px 1fr 320px");
    });
  });

  // ---- 2. DefinePanel rendering ----

  describe("DefinePanel rendering", () => {
    it("shows vision warning when visionStatus is 'missing'", () => {
      render(<DefinePanel define={{ ...defineFixture, visionStatus: "missing" }} />);
      expect(screen.getByText(/Vision not defined/i)).toBeInTheDocument();
    });

    it("renders draft spec names", () => {
      render(<DefinePanel define={defineFixture} />);
      expect(screen.getByText("auth-spec")).toBeInTheDocument();
    });

    it("renders defect severity badges", () => {
      render(<DefinePanel define={defineFixture} />);
      expect(screen.getByText("P0")).toBeInTheDocument();
      expect(screen.getByText("P2")).toBeInTheDocument();
    });
  });

  // ---- 3. JudgePanel rendering ----

  describe("JudgePanel rendering", () => {
    it("renders hero metrics: coverage, criteria, verdict, decisions", () => {
      render(<JudgePanel judge={judgeFixture} narrative={null} />);
      expect(screen.getByText("78%")).toBeInTheDocument();
      expect(screen.getByText("7/10")).toBeInTheDocument();
      expect(screen.getByText("pass")).toBeInTheDocument();
    });

    it("navigates to /outcome-review?feature=<name> on CTA click", () => {
      render(<JudgePanel judge={judgeFixture} narrative={null} />);
      fireEvent.click(screen.getByRole("button", { name: /review & decide/i }));
      expect(mockPush).toHaveBeenCalledWith("/outcome-review?feature=auth-v2");
    });
  });

  // ---- 4. ExecutePanel rendering ----

  describe("ExecutePanel rendering", () => {
    it("renders running feature name and progress percentage", () => {
      render(<ExecutePanel execute={executeFixture} onRespondToEscalation={mockOnRespond} />);
      expect(screen.getByText("auth-v2")).toBeInTheDocument();
      expect(screen.getByText("65%")).toBeInTheDocument();
    });

    it("renders progress fill bar with correct width", () => {
      const { container } = render(
        <ExecutePanel execute={executeFixture} onRespondToEscalation={mockOnRespond} />
      );
      const fillBar = Array.from(container.querySelectorAll<HTMLElement>("div[style]")).find(
        (el) => el.style.width === "65%"
      );
      expect(fillBar).toBeTruthy();
    });

    it("calls onRespondToEscalation with correct args on Send", async () => {
      render(<ExecutePanel execute={executeFixture} onRespondToEscalation={mockOnRespond} />);
      const input = screen.getByPlaceholderText("Your response\u2026");
      fireEvent.change(input, { target: { value: "Use PKCE" } });
      fireEvent.click(screen.getByRole("button", { name: /send/i }));
      await waitFor(() => {
        expect(mockOnRespond).toHaveBeenCalledWith("auth-v2", "task-5", "Use PKCE");
      });
    });
  });

  // ---- 5. LearnPanel rendering ----

  describe("LearnPanel rendering", () => {
    it("renders coverage trend sorted descending by percentage", () => {
      render(<LearnPanel {...learnFixture} />);
      // Expected order after sort: auth (90) → notifications (60) → billing (40)
      const cells = screen.getAllByText(/^(auth|notifications|billing)$/);
      expect(cells[0].textContent).toBe("auth");
      expect(cells[1].textContent).toBe("notifications");
      expect(cells[2].textContent).toBe("billing");
    });

    it("renders green dot for good insight type", () => {
      render(<LearnPanel {...learnFixture} />);
      const dot = screen.getByLabelText("good");
      expect(dot).toHaveStyle({ backgroundColor: "var(--color-emerald)" });
    });

    it("renders amber dot for warn insight type", () => {
      render(<LearnPanel {...learnFixture} />);
      const dot = screen.getByLabelText("warning");
      expect(dot).toHaveStyle({ backgroundColor: "var(--color-amber)" });
    });
  });

  // ---- 6. Empty states ----

  describe("Empty states", () => {
    it("DefinePanel shows 'Nothing to review.' with defined vision and empty arrays", () => {
      render(
        <DefinePanel
          define={{ visionStatus: "defined", draftSpecs: [], defects: [], defectCount: 0 }}
        />
      );
      expect(screen.getByText("Nothing to review.")).toBeInTheDocument();
    });

    it("JudgePanel shows 'No reviews pending' when pendingReview is null", () => {
      render(<JudgePanel judge={{ pendingReview: null, lastCompleted: null }} narrative={null} />);
      expect(screen.getByText("No reviews pending")).toBeInTheDocument();
    });

    it("ExecutePanel shows 'No features running.' with empty arrays", () => {
      render(
        <ExecutePanel
          execute={{ runningFeatures: [], escalations: [] }}
          onRespondToEscalation={mockOnRespond}
        />
      );
      expect(screen.getByText("No features running.")).toBeInTheDocument();
    });

    it("LearnPanel shows 'No learning data yet.' with empty arrays", () => {
      render(<LearnPanel coverageTrend={[]} insights={[]} escalationTrend={[]} />);
      expect(screen.getByText("No learning data yet.")).toBeInTheDocument();
    });
  });

  // ---- 7. Page integration ----

  describe("Page integration", () => {
    it("shows loading skeleton when fetching", () => {
      setupUrqlHooks({ fetching: true, data: null });
      const { container } = render(<Home />);
      expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
      expect(screen.queryByText("Define")).not.toBeInTheDocument();
    });

    it("renders all four panels when data loads successfully", () => {
      setupUrqlHooks();
      render(<Home />);
      expect(screen.getByText("Define")).toBeInTheDocument();
      expect(screen.getByText("Judge")).toBeInTheDocument();
      expect(screen.getByText("Execute")).toBeInTheDocument();
      expect(screen.getByText("Learn")).toBeInTheDocument();
    });
  });
});
