import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AuthoringSession } from "@/lib/graphql/queries/authoring";

const mockPush = vi.fn();
const mockReplace = vi.fn();
const mockRefetch = vi.fn();
const mockExecuteReplan = vi.fn();
const mockExecuteAnswer = vi.fn();
const mockExecuteAnswers = vi.fn();
let querySession: AuthoringSession;
let queryData: { authoringSession: AuthoringSession };

vi.mock("next/navigation", () => ({
  useParams: () => ({ feature: "provisional-route-slug", artifact: "prd" }),
  useRouter: () => ({ push: mockPush, replace: mockReplace }),
}));

vi.mock("urql", () => ({
  gql: (strings: TemplateStringsArray) => strings.raw.join(""),
  useQuery: () => [{ data: queryData, fetching: false, error: null }, mockRefetch],
  useSubscription: () => [{ data: null, fetching: false, error: null }],
  useMutation: (query: string) => [
    { data: null, fetching: false, error: null },
    query.includes("ReplanAuthoring")
      ? mockExecuteReplan
      : query.includes("SubmitAuthoringAnswers")
        ? mockExecuteAnswers
      : query.includes("SubmitAuthoringAnswer")
        ? mockExecuteAnswer
        : vi.fn(),
  ],
}));

vi.mock("@/components/landing/IconRail", () => ({ IconRail: () => null }));
vi.mock("@/components/layout/header", () => ({ Header: () => null }));

import AuthoringPage from "@/app/define/[feature]/authoring/[artifact]/page";

const baseSession = (overrides: Partial<AuthoringSession> = {}): AuthoringSession => ({
  status: "question",
  featureName: "provisional-route-slug",
  featureTitle: "When the user adds the task they will have",
  artifactType: "prd",
  questionBankVersion: "prd-v4",
  revision: 0,
  message: "",
  progress: { confirmed: 0, total: 3, deferred: [] },
  draftAvailable: false,
  artifactPath: null,
  artifactContent: null,
  dashboardUrl: null,
  authoringUrl: null,
  helperPath: null,
  interpreter: null,
  currentQuestion: null,
  coverage: {},
  sections: [],
  intake: { feature_description: "Add optional task due dates and prioritize urgent work." },
  interview: [],
  selfReview: null,
  resumeStep: null,
  implementation: null,
  planning: {
    mode: "fallback",
    planner_version: null,
    analysis_summary: "Deterministic helper planning is active.",
    questions: [],
  },
  versions: [],
  publishedRevision: null,
  publishHistory: [],
  ...overrides,
});

describe("authoring AI planning transition", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    querySession = baseSession();
    queryData = { authoringSession: querySession };
  });

  it("keeps the title pending and renders planned questions after an equivalent query refresh", async () => {
    let finishPlanning: ((value: unknown) => void) | undefined;
    mockExecuteReplan.mockReturnValue(new Promise((resolve) => {
      finishPlanning = resolve;
    }));

    const view = render(<AuthoringPage />);

    await waitFor(() => expect(mockExecuteReplan).toHaveBeenCalledOnce());
    expect(screen.getAllByText("Deriving title…").length).toBeGreaterThan(0);
    expect(screen.queryByText("When the user adds the task they will have")).not.toBeInTheDocument();
    expect(screen.queryByText("Deterministic helper planning is active.")).not.toBeInTheDocument();

    // A route-transition/cache refresh can deliver an equivalent session
    // object while the model request is still in flight.
    querySession = baseSession();
    queryData = { authoringSession: querySession };
    view.rerender(<AuthoringPage />);

    const question = {
      id: "P-Q4",
      prompt: "How should overdue tasks behave?",
      evidence: "The brief defines due dates but not overdue ordering.",
      purpose: "Confirm overdue behavior.",
      completion_evidence: "Ordering and emphasis are explicit.",
      response_control: {
        id: "model-answer-p-q4",
        input_type: "single_select" as const,
        prompt: "Choose the closest answer or write your own.",
        initial_value: "",
        options: [
          { value: "Overdue tasks sort first.", label: "Sort overdue first" },
          { value: "Keep the current order.", label: "Keep current order" },
        ],
        submit_action: "answer",
        allow_other: true,
      },
      suggestion: null,
      existing_answer: null,
      follow_up: null,
      edit_request: null,
      review_findings: [],
    };
    const planned = baseSession({
      featureName: "optional-task-due-dates",
      featureTitle: "Optional Task Due Dates",
      intake: {
        feature_title: "Optional Task Due Dates",
        feature_description: "Add optional task due dates and prioritize urgent work.",
      },
      // Planning rewrites the provisional artifact and therefore advances the
      // checkpoint. The still-cached query result remains at revision 0.
      revision: 1,
      currentQuestion: question,
      planning: {
        mode: "model",
        planner_version: "model-prd-v5",
        analysis_summary: "The brief covers the core behavior; overdue handling needs confirmation.",
        questions: [question],
      },
    });

    await act(async () => {
      finishPlanning?.({ data: { replanAuthoring: planned }, error: null });
    });

    expect((await screen.findAllByText("Optional Task Due Dates")).length).toBeGreaterThan(0);
    expect(screen.getByText("How should overdue tasks behave?")).toBeInTheDocument();
    expect(screen.queryByText("Deriving title…")).not.toBeInTheDocument();
    expect(screen.queryByText(/This draft changed before your update finished/)).not.toBeInTheDocument();
    expect(mockReplace).toHaveBeenCalledWith(
      "/define/optional-task-due-dates/authoring/prd",
    );
  });

  it("keeps an established AI title visible if a later operation falls back", async () => {
    querySession = baseSession({
      status: "drafted",
      featureTitle: "Optional Task Due Dates",
      revision: 8,
      progress: { confirmed: 3, total: 3, deferred: [] },
      intake: {
        feature_title: "Optional Task Due Dates",
        feature_description: "Add optional task due dates and prioritize urgent work.",
      },
      planning: {
        mode: "fallback",
        planner_version: "model-prd-v5",
        fallback_reason: "A later completeness check was unavailable.",
        questions: [],
      },
    });
    queryData = { authoringSession: querySession };

    render(<AuthoringPage />);

    expect((await screen.findAllByText("Optional Task Due Dates")).length).toBeGreaterThan(0);
    expect(screen.queryByText("Title unavailable")).not.toBeInTheDocument();
  });

  it("does not replan a published artifact when the page opens", async () => {
    querySession = baseSession({
      status: "published",
      revision: 8,
      publishedRevision: 8,
    });
    queryData = { authoringSession: querySession };

    render(<AuthoringPage />);

    await waitFor(() => expect(screen.getByText("PRD published")).toBeInTheDocument());
    expect(screen.queryByText("rev 8")).not.toBeInTheDocument();
    expect(mockExecuteReplan).not.toHaveBeenCalled();
  });

  it("does not show an internal artifact until the interview has produced a terminal draft", async () => {
    const artifactContent = [
      "# PRD: Optional Task Due Dates",
      "",
      "## Summary",
      "",
      "A partial artifact that must stay hidden during the interview.",
    ].join("\n");
    querySession = baseSession({
      status: "question",
      draftAvailable: true,
      artifactPath: "specs/optional-task-due-dates/prd.md",
      artifactContent,
      planning: {
        mode: "model",
        planner_version: "model-prd-v5",
        analysis_summary: "One material decision still needs confirmation.",
        questions: [],
      },
    });
    queryData = { authoringSession: querySession };

    const view = render(<AuthoringPage />);

    expect(screen.queryByText("A partial artifact that must stay hidden during the interview.")).not.toBeInTheDocument();

    querySession = baseSession({
      status: "drafted",
      revision: 1,
      progress: { confirmed: 3, total: 3, deferred: [] },
      draftAvailable: true,
      artifactPath: "specs/optional-task-due-dates/prd.md",
      artifactContent,
      interview: [
        {
          id: "P-Q4",
          prompt: "How should overdue tasks behave?",
          answer: "Overdue tasks sort first.",
          state: "confirmed",
        },
      ],
      sections: [{ title: "Summary", question_ids: [], coverage_ids: [], state: "generated" }],
      versions: [{ revision: 1, content: artifactContent }],
      planning: {
        mode: "model",
        planner_version: "model-prd-v5",
        analysis_summary: "Every material decision is confirmed.",
        questions: [],
      },
    });
    queryData = { authoringSession: querySession };
    view.rerender(<AuthoringPage />);

    expect(await screen.findByText("A partial artifact that must stay hidden during the interview.")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Questions and answers" })).toBeInTheDocument();
    expect(screen.getByText("Overdue tasks sort first.")).toBeInTheDocument();
  });

  it("shows structural repair in the editor without calling it V1-ready", async () => {
    const artifactContent = [
      "# PRD: Optional Task Due Dates",
      "",
      "## Summary",
      "",
      "Repair this generated summary table.",
    ].join("\n");
    querySession = baseSession({
      status: "review_repair",
      revision: 4,
      draftAvailable: true,
      artifactPath: "specs/optional-task-due-dates/prd.md",
      artifactContent,
      currentQuestion: null,
      progress: { confirmed: 3, total: 3, deferred: [] },
      sections: [{ title: "Summary", question_ids: [], coverage_ids: [], state: "manual" }],
      versions: [{ revision: 4, content: artifactContent }],
      selfReview: {
        status: "needs_repair",
        pass_count: 1,
        findings: [{
          question_id: null,
          kind: "invalid_table",
          message: "Markdown table near line 20 has inconsistent columns.",
        }],
      },
      planning: {
        mode: "model",
        planner_version: "model-prd-v5",
        analysis_summary: "Interview complete; structural repair is required.",
        questions: [],
      },
      message: "The generated draft needs a structural repair before V1 is ready.",
    });
    queryData = { authoringSession: querySession };

    render(<AuthoringPage />);

    expect(await screen.findByText("Draft needs repair before V1")).toBeInTheDocument();
    expect(screen.getByText("Repair this generated summary table.")).toBeInTheDocument();
    expect(screen.getByText("Fix in editor")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Publish" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Review & commit/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/V1 ready/)).not.toBeInTheDocument();
  });

  it("persists each planned answer before advancing the interview", async () => {
    const firstQuestion = {
      id: "P-Q2",
      prompt: "Who should use the net worth dashboard?",
      evidence: "The description refers to an individual.",
      purpose: "Confirm the user boundary.",
      response_control: {
        id: "model-answer-p-q2",
        input_type: "single_select" as const,
        prompt: "Choose the closest answer or write your own.",
        initial_value: "",
        options: [
          { value: "One individual manages only their own finances.", label: "Personal dashboard" },
          { value: "An advisor manages finances for multiple clients.", label: "Advisor dashboard" },
        ],
        submit_action: "answer",
        allow_other: true,
      },
      suggestion: null,
      review_findings: [],
    };
    const secondQuestion = {
      ...firstQuestion,
      id: "P-Q4",
      prompt: "How are balances entered?",
      response_control: {
        ...firstQuestion.response_control,
        id: "model-answer-p-q4",
        options: [
          { value: "Balances are entered manually.", label: "Manual entry" },
          { value: "Balances are synced automatically.", label: "Automatic sync" },
        ],
      },
    };
    querySession = baseSession({
      featureTitle: "Net Worth Dashboard",
      revision: 3,
      currentQuestion: firstQuestion,
      planning: {
        mode: "model",
        planner_version: "model-prd-v5",
        analysis_summary: "Two material product decisions still need confirmation.",
        questions: [firstQuestion, secondQuestion],
      },
    });
    queryData = { authoringSession: querySession };
    mockExecuteAnswer.mockResolvedValue({
      data: { submitAuthoringAnswer: querySession },
      error: null,
    });

    render(<AuthoringPage />);
    fireEvent.click(await screen.findByRole("radio", { name: /Personal dashboard/ }));
    fireEvent.click(screen.getByRole("button", { name: "Save & continue" }));

    await waitFor(() => expect(mockExecuteAnswer).toHaveBeenCalledWith({
      featureName: "provisional-route-slug",
      artifactType: "prd",
      questionId: "P-Q2",
      answer: "One individual manages only their own finances.",
      expectedRevision: 3,
    }));
    expect(mockExecuteAnswers).not.toHaveBeenCalled();
  });
});
