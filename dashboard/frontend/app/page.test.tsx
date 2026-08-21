import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import type { LandingViewData } from "@/lib/graphql/queries/landing";

// Mock urql hooks
const mockReexecQuery = vi.fn();
const mockExecuteMutation = vi.fn();

vi.mock("urql", () => ({
  gql: (strings: TemplateStringsArray) => strings.raw.join(""),
  useQuery: vi.fn(),
  useMutation: vi.fn(),
  useSubscription: vi.fn(),
}));

// Capture the onRespondToEscalation handler passed to ExecutePanel
let capturedEscalationHandler: ((f: string, t: string, r: string) => Promise<void>) | null = null;

vi.mock("@/components/landing/TopBar", () => ({
  TopBar: ({ projectName, branch }: { projectName: string; branch: string }) => (
    <div data-testid="topbar">{projectName} / {branch}</div>
  ),
}));

vi.mock("@/components/landing/EditorialGrid", () => ({
  EditorialGrid: ({ definePanel, judgePanel, executePanel, learnPanel }: Record<string, React.ReactNode>) => (
    <div data-testid="editorial-grid">
      <div data-testid="slot-define">{definePanel}</div>
      <div data-testid="slot-judge">{judgePanel}</div>
      <div data-testid="slot-execute">{executePanel}</div>
      <div data-testid="slot-learn">{learnPanel}</div>
    </div>
  ),
}));

vi.mock("@/components/landing/DefinePanel", () => ({
  DefinePanel: () => <div data-testid="define-panel">DefinePanel</div>,
}));

vi.mock("@/components/landing/JudgePanel", () => ({
  JudgePanel: () => <div data-testid="judge-panel">JudgePanel</div>,
}));

vi.mock("@/components/landing/ExecutePanel", () => ({
  ExecutePanel: ({ onRespondToEscalation }: { execute: unknown; onRespondToEscalation: (f: string, t: string, r: string) => Promise<void> }) => {
    capturedEscalationHandler = onRespondToEscalation;
    return <div data-testid="execute-panel">ExecutePanel</div>;
  },
}));

vi.mock("@/components/landing/LearnPanel", () => ({
  LearnPanel: () => <div data-testid="learn-panel">LearnPanel</div>,
}));

vi.mock("@/components/landing/StatusBar", () => ({
  StatusBar: ({ connected, projectName }: { connected: boolean; projectName: string }) => (
    <div data-testid="status-bar" data-connected={connected} data-project={projectName}>
      StatusBar
    </div>
  ),
}));

vi.mock("@/components/shared/loading-skeleton", () => ({
  Skeleton: ({ className }: { className?: string }) => (
    <div data-testid="skeleton" className={className} />
  ),
}));

import { useQuery, useMutation, useSubscription } from "urql";
import Home from "./page";

const mockedUseQuery = vi.mocked(useQuery);
const mockedUseMutation = vi.mocked(useMutation);
const mockedUseSubscription = vi.mocked(useSubscription);

const baseLandingView: LandingViewData = {
  landingView: {
    greeting: "Good morning",
    projectName: "speed",
    branch: "main",
    narrative: "All systems nominal",
    define: {
      visionStatus: "complete",
      draftSpecs: [{ name: "auth", specTypes: ["product"], status: "ready" }],
      defects: [],
      defectCount: 0,
    },
    judge: {
      pendingReview: null,
      lastCompleted: null,
    },
    execute: {
      runningFeatures: [
        { name: "auth", progressPct: 50, tasksCompleted: 5, tasksTotal: 10, blockedCount: 0 },
      ],
      escalations: [],
    },
    learn: {
      coverageTrend: [{ feature: "auth", coveragePct: 80 }],
      insights: [{ type: "good", text: "Coverage improving" }],
      escalationTrend: [{ feature: "auth", count: 1 }],
    },
  },
};

function setupHooks(overrides: {
  fetching?: boolean;
  error?: Error | null;
  data?: LandingViewData | null;
  subData?: { taskStatusChanged?: { feature: string; taskId: string; status: string } } | null;
  subError?: Error | null;
} = {}) {
  const {
    fetching = false,
    error = null,
    data = baseLandingView,
    subData = null,
    subError = null,
  } = overrides;

  mockedUseQuery.mockReturnValue([
    { data, fetching, error, stale: false, extensions: undefined } as ReturnType<typeof useQuery>[0],
    mockReexecQuery,
  ] as unknown as ReturnType<typeof useQuery>);

  mockedUseMutation.mockReturnValue([
    { fetching: false, stale: false, error: undefined, extensions: undefined, data: undefined },
    mockExecuteMutation,
  ] as unknown as ReturnType<typeof useMutation>);

  mockedUseSubscription.mockReturnValue([
    { data: subData, error: subError, fetching: false, stale: false, extensions: undefined } as ReturnType<typeof useSubscription>[0],
    vi.fn(),
  ] as unknown as ReturnType<typeof useSubscription>);
}

describe("Home (landing page)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    capturedEscalationHandler = null;
  });

  describe("loading state", () => {
    it("renders skeleton grid with four skeleton panels", () => {
      setupHooks({ fetching: true, data: null });
      render(<Home />);

      const skeletons = screen.getAllByTestId("skeleton");
      expect(skeletons.length).toBeGreaterThan(0);
      expect(screen.getByTestId("editorial-grid")).toBeInTheDocument();
    });

    it("renders StatusBar in loading state", () => {
      setupHooks({ fetching: true, data: null });
      render(<Home />);

      const statusBar = screen.getByTestId("status-bar");
      expect(statusBar).toBeInTheDocument();
      expect(statusBar).toHaveAttribute("data-connected", "false");
    });

    it("does not render TopBar while loading", () => {
      setupHooks({ fetching: true, data: null });
      render(<Home />);

      expect(screen.queryByTestId("topbar")).not.toBeInTheDocument();
    });
  });

  describe("error state", () => {
    it("shows error banner with network error message", () => {
      setupHooks({ error: new Error("Network failure"), data: null });
      render(<Home />);

      expect(screen.getByText("Network failure")).toBeInTheDocument();
    });

    it("shows fallback error message when landingView is null", () => {
      setupHooks({ data: { landingView: null } as unknown as LandingViewData });
      render(<Home />);

      expect(screen.getByText("Failed to load landing data")).toBeInTheDocument();
    });

    it("renders empty panels in editorial grid on error", () => {
      setupHooks({ error: new Error("fail"), data: null });
      render(<Home />);

      expect(screen.getByTestId("editorial-grid")).toBeInTheDocument();
      expect(screen.queryByTestId("define-panel")).not.toBeInTheDocument();
    });

    it("renders StatusBar as disconnected on error", () => {
      setupHooks({ error: new Error("fail"), data: null });
      render(<Home />);

      const statusBar = screen.getByTestId("status-bar");
      expect(statusBar).toHaveAttribute("data-connected", "false");
      expect(statusBar).toHaveAttribute("data-project", "");
    });
  });

  describe("successful render", () => {
    it("renders all four panel components", () => {
      setupHooks();
      render(<Home />);

      expect(screen.getByTestId("define-panel")).toBeInTheDocument();
      expect(screen.getByTestId("judge-panel")).toBeInTheDocument();
      expect(screen.getByTestId("execute-panel")).toBeInTheDocument();
      expect(screen.getByTestId("learn-panel")).toBeInTheDocument();
    });

    it("renders TopBar with project name and branch", () => {
      setupHooks();
      render(<Home />);

      const topbar = screen.getByTestId("topbar");
      expect(topbar).toHaveTextContent("speed");
      expect(topbar).toHaveTextContent("main");
    });

    it("renders StatusBar with connected state and project info", () => {
      setupHooks();
      render(<Home />);

      const statusBar = screen.getByTestId("status-bar");
      expect(statusBar).toHaveAttribute("data-connected", "true");
      expect(statusBar).toHaveAttribute("data-project", "speed");
    });

    it("falls back to empty string when branch is null", () => {
      const data = structuredClone(baseLandingView);
      data.landingView.branch = null;
      setupHooks({ data });
      render(<Home />);

      const topbar = screen.getByTestId("topbar");
      expect(topbar).toHaveTextContent("speed /");
    });

    it("renders page at root route via Next.js app/page.tsx convention", () => {
      setupHooks();
      const { container } = render(<Home />);
      expect(container.firstChild).toBeTruthy();
    });
  });

  describe("escalation mutation", () => {
    it("refetches landing data on successful escalation", async () => {
      mockExecuteMutation.mockResolvedValueOnce({
        data: { respondToEscalation: { success: true, error: null } },
      });

      setupHooks();
      render(<Home />);

      expect(capturedEscalationHandler).toBeTruthy();
      await capturedEscalationHandler!("auth", "task-1", "Yes, use OAuth");

      expect(mockExecuteMutation).toHaveBeenCalledWith({
        feature: "auth",
        taskId: "task-1",
        response: "Yes, use OAuth",
      });

      await waitFor(() => {
        expect(mockReexecQuery).toHaveBeenCalledWith({ requestPolicy: "network-only" });
      });
    });

    it("does not refetch when mutation returns success=false", async () => {
      mockExecuteMutation.mockResolvedValueOnce({
        data: { respondToEscalation: { success: false, error: "denied" } },
      });

      setupHooks();
      render(<Home />);

      expect(capturedEscalationHandler).toBeTruthy();
      await capturedEscalationHandler!("auth", "task-1", "No");

      expect(mockExecuteMutation).toHaveBeenCalled();
      expect(mockReexecQuery).not.toHaveBeenCalled();
    });
  });

  describe("subscription", () => {
    it("triggers refetch when taskStatusChanged fires", () => {
      setupHooks({
        subData: { taskStatusChanged: { feature: "auth", taskId: "t-1", status: "done" } },
      });
      render(<Home />);

      expect(mockReexecQuery).toHaveBeenCalledWith({ requestPolicy: "network-only" });
    });

    it("does not refetch when subscription data is null", () => {
      setupHooks({ subData: null });
      render(<Home />);

      expect(mockReexecQuery).not.toHaveBeenCalled();
    });

    it("shows connected=true when no running features (subscription paused)", () => {
      const data = structuredClone(baseLandingView);
      data.landingView.execute.runningFeatures = [];
      setupHooks({ data });
      render(<Home />);

      const statusBar = screen.getByTestId("status-bar");
      expect(statusBar).toHaveAttribute("data-connected", "true");
    });

    it("shows connected=false when subscription has an error", () => {
      setupHooks({ subError: new Error("ws closed") });
      render(<Home />);

      const statusBar = screen.getByTestId("status-bar");
      expect(statusBar).toHaveAttribute("data-connected", "false");
    });
  });

  describe("null safety", () => {
    it("handles empty arrays in all panels without crashing", () => {
      const data: LandingViewData = {
        landingView: {
          greeting: "Hello",
          projectName: "test",
          branch: null,
          narrative: null,
          define: { visionStatus: "missing", draftSpecs: [], defects: [], defectCount: 0 },
          judge: { pendingReview: null, lastCompleted: null },
          execute: { runningFeatures: [], escalations: [] },
          learn: { coverageTrend: [], insights: [], escalationTrend: [] },
        },
      };
      setupHooks({ data });

      expect(() => render(<Home />)).not.toThrow();
      expect(screen.getByTestId("define-panel")).toBeInTheDocument();
      expect(screen.getByTestId("judge-panel")).toBeInTheDocument();
      expect(screen.getByTestId("execute-panel")).toBeInTheDocument();
      expect(screen.getByTestId("learn-panel")).toBeInTheDocument();
    });
  });
});
