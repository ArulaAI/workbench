import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SourceInputPanel } from "@/components/ceremony/guided";

describe("SourceInputPanel", () => {
  it("shows the original intake and the actual questions with their answers", () => {
    render(
      <SourceInputPanel
        expanded
        intake={{
          feature_title: "Due dates for tasks",
          feature_description: "Tasks currently have no due date.",
        }}
        interview={[
          {
            id: "P-Q4",
            prompt: "Walk me through the essential journey.",
            answer: "The user selects an optional date while editing a task.",
            state: "confirmed",
          },
        ]}
      />,
    );

    expect(screen.getByText("Due dates for tasks")).toBeInTheDocument();
    expect(screen.getByText("Tasks currently have no due date.")).toBeInTheDocument();
    expect(screen.getByText("Walk me through the essential journey.")).toBeInTheDocument();
    expect(
      screen.getByText("The user selects an optional date while editing a task."),
    ).toBeInTheDocument();
    expect(screen.getByText("1 answered question")).toBeInTheDocument();
  });
});
