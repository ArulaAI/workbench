import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { QuestionBatch, QuestionCard } from "@/components/ceremony/guided";
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

const MODEL_CHOICE_QUESTION: CurrentQuestion = {
  ...ACTION_QUESTION,
  id: "P-Q2",
  prompt: "What should happen to tasks that do not have a due date?",
  suggestion: {
    id: "model-p-q2-0",
    answer: "Existing and new undated tasks remain valid and unchanged.",
    confidence: "partial",
    sources: [],
    gaps: ["Confirm the backward-compatible default."],
  },
  response_control: {
    id: "model-answer-p-q2",
    input_type: "multi_select",
    prompt: "Choose the behavior that should apply.",
    submit_action: "answer",
    allow_other: true,
    options: [
      {
        label: "Keep undated tasks valid",
        value: "Existing and new undated tasks remain valid and unchanged.",
        recommended: true,
      },
      {
        label: "Show undated tasks last",
        value: "Undated tasks appear after tasks that have a due date.",
      },
    ],
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
  it("renders the prompt, evidence, and only the returned options", () => {
    renderCard(ACTION_QUESTION);

    expect(screen.getByText(ACTION_QUESTION.prompt)).toBeInTheDocument();
    expect(screen.getByText(/Confirmed flows/)).toBeInTheDocument();
    const options = screen.getAllByRole("radio");
    expect(options.map((option) => option.textContent)).toEqual([
      "Answer question",
      "Defer",
    ]);
    expect(screen.queryByText("Accept suggestion")).not.toBeInTheDocument();
  });

  it("does not present an empty suggestion as useful guidance", () => {
    renderCard(ACTION_QUESTION);
    expect(screen.queryByLabelText(/Suggested response/)).not.toBeInTheDocument();
    expect(screen.queryByText(/does not resolve this decision/)).not.toBeInTheDocument();
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
    fireEvent.click(screen.getByRole("button", { name: "Save answer" }));
    expect(props.onAnswer).toHaveBeenCalledWith("A prefilled suggestion.");
  });

  it("does not submit whitespace-only answers", () => {
    const props = renderCard(TEXT_QUESTION, { draftText: "   " });

    const submit = screen.getByRole("button", { name: "Save answer" });
    expect(submit).toBeDisabled();
    fireEvent.click(submit);
    expect(props.onAnswer).not.toHaveBeenCalled();
  });

  it("submits contextual model choices as complete answer text", () => {
    const props = renderCard(MODEL_CHOICE_QUESTION);

    fireEvent.click(screen.getByRole("checkbox", { name: /Keep undated tasks valid/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Show undated tasks last/ }));
    fireEvent.click(screen.getByRole("button", { name: "Save answer" }));

    expect(props.onAnswer).toHaveBeenCalledWith(
      "Existing and new undated tasks remain valid and unchanged.\n" +
        "Undated tasks appear after tasks that have a due date.",
    );
    expect(screen.getByText("Suggested")).toBeInTheDocument();
    expect(screen.getByText(/Select every statement that should apply/)).toBeInTheDocument();
  });

  it("includes selected choices when Cmd+Enter submits an Other answer", () => {
    const props = renderCard(MODEL_CHOICE_QUESTION);

    fireEvent.click(screen.getByRole("checkbox", { name: /Keep undated tasks valid/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Other/ }));
    const other = screen.getByRole("textbox", { name: "Your answer" });
    fireEvent.change(other, { target: { value: "Undated tasks can be filtered separately." } });
    fireEvent.keyDown(other, { key: "Enter", metaKey: true });

    expect(props.onAnswer).toHaveBeenCalledWith(
      "Existing and new undated tasks remain valid and unchanged.\n" +
        "Undated tasks can be filtered separately.",
    );
  });

  it("persists the current planned answer before the server advances", () => {
    const onSubmit = vi.fn();
    render(
      <QuestionBatch
        questions={[TEXT_QUESTION, MODEL_CHOICE_QUESTION]}
        revision={0}
        submitting={false}
        onSubmit={onSubmit}
      />,
    );

    expect(screen.getByText(/These 2 questions were identified together/)).toBeInTheDocument();
    expect(screen.getByText(TEXT_QUESTION.prompt)).toBeInTheDocument();
    expect(screen.queryByText(MODEL_CHOICE_QUESTION.prompt)).not.toBeInTheDocument();
    expect(screen.getByText("1/2")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Save & continue" }));

    expect(screen.queryByRole("button", { name: "Create PRD" })).not.toBeInTheDocument();
    expect(onSubmit).toHaveBeenCalledWith({
      question_id: "P-Q5",
      answer: "A prefilled suggestion.",
    });
    // The next question is rendered only after the persisted server checkpoint
    // is returned; it is never advanced optimistically in browser memory.
    expect(screen.getByText(TEXT_QUESTION.prompt)).toBeInTheDocument();
    expect(screen.queryByText(MODEL_CHOICE_QUESTION.prompt)).not.toBeInTheDocument();
  });

  it("does not expose browser-only navigation for unsaved prepared answers", () => {
    render(
      <QuestionBatch
        questions={[TEXT_QUESTION, MODEL_CHOICE_QUESTION]}
        revision={0}
        submitting={false}
        onSubmit={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Previous question" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next question" })).toBeDisabled();
  });

  it("uses neutral PRD creation copy without an AI label", () => {
    const { rerender } = render(
      <QuestionBatch
        questions={[TEXT_QUESTION]}
        revision={0}
        submitting={false}
        onSubmit={vi.fn()}
      />,
    );
    rerender(
      <QuestionBatch
        questions={[TEXT_QUESTION]}
        revision={0}
        submitting
        onSubmit={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Generating PRD…" })).toBeInTheDocument();
    expect(screen.queryByText(/with AI/i)).not.toBeInTheDocument();
  });
});
