import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { QuestionCard } from "@/components/ceremony/guided";
import type { CurrentQuestion } from "@/lib/graphql/queries/authoring";

const ACTION_QUESTION: CurrentQuestion = {
  id: "P-Q5",
  prompt: "What must task due dates do, and what observable behaviour proves it?",
  evidence: "Confirmed flows, business rules, existing contracts",
  suggestion: {
    id: "sug-1",
    answer: null,
    confidence: "partial",
    accept_ready: false,
    sources: [
      {
        id: "intake:feature-description",
        path: ".speed/features/task-due-dates/authoring-prd.json",
        status: "available",
        excerpt: "Team leads cannot see overdue work.",
      },
    ],
    gaps: ["Available evidence provides context but does not resolve this decision."],
  },
  response_control: {
    id: "suggestion_action",
    input_type: "single_select",
    prompt: "How would you like to respond?",
    options: [
      { value: "edit", label: "Answer question" },
      { value: "defer", label: "Defer" },
    ],
  },
  review_findings: [],
};

const TEXT_QUESTION: CurrentQuestion = {
  ...ACTION_QUESTION,
  suggestion: null,
  response_control: {
    id: "edited_suggestion",
    input_type: "textarea",
    prompt: "Edit the suggested response, then submit your version.",
    initial_value: "A prefilled suggestion.",
    submit_action: "answer",
  },
};

function renderCard(question: CurrentQuestion, overrides = {}) {
  const props = {
    question,
    revision: 2,
    submitting: false,
    draftText: "",
    onDraftTextChange: vi.fn(),
    onAction: vi.fn(),
    onAnswer: vi.fn(),
    ...overrides,
  };
  render(<QuestionCard {...props} />);
  return props;
}

describe("QuestionCard", () => {
  it("renders the helper's prompt, evidence, gaps, and only the returned options", () => {
    renderCard(ACTION_QUESTION);

    expect(screen.getByText(ACTION_QUESTION.prompt)).toBeInTheDocument();
    expect(screen.getByText(/Confirmed flows/)).toBeInTheDocument();
    expect(screen.getByText(/does not resolve this decision/)).toBeInTheDocument();
    const options = screen.getAllByRole("radio");
    expect(options.map((option) => option.textContent)).toEqual([
      "Answer question",
      "Defer",
    ]);
    expect(screen.queryByText("Accept suggestion")).not.toBeInTheDocument();
  });

  it("states plainly when no grounded response is available", () => {
    renderCard(ACTION_QUESTION);
    expect(
      screen.getByText("No grounded response is available for this question."),
    ).toBeInTheDocument();
  });

  it("requires an explicit continue before acting on a selection", () => {
    const props = renderCard(ACTION_QUESTION);

    fireEvent.click(screen.getByRole("radio", { name: /Defer/ }));
    expect(props.onAction).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(props.onAction).toHaveBeenCalledWith("DEFER");
  });

  it("keeps Continue disabled until an option is selected", () => {
    renderCard(ACTION_QUESTION);
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
  });

  it("prefills the textarea from the control and submits its text", () => {
    const props = renderCard(TEXT_QUESTION, { draftText: "A prefilled suggestion." });

    expect(props.onDraftTextChange).toHaveBeenCalledWith("A prefilled suggestion.");
    fireEvent.click(screen.getByRole("button", { name: "Confirm answer" }));
    expect(props.onAnswer).toHaveBeenCalledWith("A prefilled suggestion.");
  });

  it("does not submit whitespace-only answers", () => {
    const props = renderCard(TEXT_QUESTION, { draftText: "   " });

    const submit = screen.getByRole("button", { name: "Confirm answer" });
    expect(submit).toBeDisabled();
    fireEvent.click(submit);
    expect(props.onAnswer).not.toHaveBeenCalled();
  });
});
