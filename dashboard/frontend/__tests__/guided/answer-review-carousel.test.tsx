import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AnswerReviewCarousel } from "@/components/ceremony/guided";

const answers = [
  {
    id: "P-Q2",
    prompt: "Who is this product for?",
    answer: "Individual users.",
    state: "confirmed",
  },
  {
    id: "P-Q4",
    prompt: "How should overdue tasks behave?",
    answer: "Overdue tasks sort first.",
    state: "confirmed",
  },
];

describe("AnswerReviewCarousel", () => {
  it("shows one submitted answer at a time and supports review navigation", () => {
    render(<AnswerReviewCarousel answers={answers} />);

    expect(screen.getByText("Your answers")).toBeInTheDocument();
    expect(screen.getByText("Who is this product for?")).toBeInTheDocument();
    expect(screen.queryByText("How should overdue tasks behave?")).not.toBeInTheDocument();
    expect(screen.getByText("1/2")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Next answer" }));

    expect(screen.getByText("How should overdue tasks behave?")).toBeInTheDocument();
    expect(screen.getByText("Overdue tasks sort first.")).toBeInTheDocument();
    expect(screen.getByText("2/2")).toBeInTheDocument();
  });

  it("can collapse the summary and sends the selected answer to edit", () => {
    const onEditAnswer = vi.fn();
    render(
      <AnswerReviewCarousel answers={answers} onEditAnswer={onEditAnswer} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(onEditAnswer).toHaveBeenCalledWith("P-Q2", "Individual users.");

    fireEvent.click(screen.getByRole("button", { name: "Questions" }));
    expect(screen.queryByText("Your answers")).not.toBeInTheDocument();
  });
});
