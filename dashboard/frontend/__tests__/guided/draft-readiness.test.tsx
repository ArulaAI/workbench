import { render, screen } from "@testing-library/react";
import { DraftReadiness } from "@/components/ceremony/guided";

describe("DraftReadiness", () => {
  it("shows value-first progress without exposing the full question checklist", () => {
    render(
      <DraftReadiness
        draftAvailable
        confirmed={1}
        currentQuestion={{
          id: "P-Q5",
          prompt: "What proves the requirement?",
          evidence: "Current behavior",
          purpose: "Make the essential behavior independently observable.",
          suggestion: null,
          response_control: { id: "answer", input_type: "textarea", prompt: "Answer" },
          review_findings: [],
        }}
        sections={[
          {
            title: "Problem & Evidence",
            question_ids: ["P-Q1"],
            coverage_ids: ["P-Q1"],
            state: "confirmed",
          },
        ]}
      />,
    );

    expect(screen.getByText("V1 draft ready")).toBeInTheDocument();
    expect(screen.getByText("1 confirmed input")).toBeInTheDocument();
    expect(screen.getByText("Problem & Evidence")).toBeInTheDocument();
    expect(screen.queryByText(/1\/8/)).not.toBeInTheDocument();
    expect(screen.queryByText("P-Q5")).not.toBeInTheDocument();
  });
});
