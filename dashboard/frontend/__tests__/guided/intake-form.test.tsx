import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ArtifactSourceIntake, ArtifactTabs, GuidedPrdIntakeForm } from "@/components/ceremony/guided";
import type { IntakeInput } from "@/lib/graphql/queries/authoring";

const input: IntakeInput = {
  id: "new_prd_basics",
  input_type: "form",
  prompt: "Tell Workbench what this new PRD should define.",
  fields: [
    {
      id: "feature_description",
      input_type: "textarea",
      prompt: "What would you like to ship?",
      required: true,
    },
  ],
};

function renderForm(overrides: Partial<React.ComponentProps<typeof GuidedPrdIntakeForm>> = {}) {
  const props: React.ComponentProps<typeof GuidedPrdIntakeForm> = {
    input,
    submitting: false,
    serverError: null,
    onSubmit: vi.fn(),
    ...overrides,
  };
  render(<GuidedPrdIntakeForm {...props} />);
  fireEvent.change(screen.getByLabelText("What would you like to ship?"), {
    target: { value: "Build due dates so managers can see overdue tasks today." },
  });
  return props;
}

describe("GuidedPrdIntakeForm", () => {
  it("submits only the description so the server can derive canonical identity", () => {
    const onSubmit = vi.fn();
    renderForm({ onSubmit });

    fireEvent.click(screen.getByRole("button", { name: "Continue" }));

    expect(onSubmit).toHaveBeenCalledWith(
      "Build due dates so managers can see overdue tasks today.",
    );
    const textarea = screen.getByLabelText("What would you like to ship?");
    expect(textarea).not.toHaveAttribute("maxlength");
    expect(screen.queryByText(/\/ 500/)).not.toBeInTheDocument();

    const longDescription = `Build due dates for managers. ${"Cover detailed validation and recovery behavior. ".repeat(14)}`;
    fireEvent.change(textarea, { target: { value: longDescription } });
    expect(textarea).toHaveValue(longDescription);
    expect(longDescription.length).toBeGreaterThan(500);
  });

  it("requires a meaningful description before continuing", () => {
    render(<GuidedPrdIntakeForm input={input} submitting={false} serverError={null} onSubmit={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("What would you like to ship?"), {
      target: { value: "Too short" },
    });
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
  });
});

describe("reusable artifact intake", () => {
  it("switches between PRD, Design, and Technical RFC", () => {
    const onChange = vi.fn();
    render(<ArtifactTabs value="prd" onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Technical RFC" }));
    expect(onChange).toHaveBeenCalledWith("rfc");
  });

  it("starts a downstream interview from an existing PRD", () => {
    const onSelect = vi.fn();
    render(
      <ArtifactSourceIntake
        artifactType="design"
        submitting={false}
        serverError={null}
        onSelect={onSelect}
        input={{
          id: "source_prd",
          input_type: "prd_reference",
          prompt: "Which PRD should ground this Design draft?",
          options: [{ feature_name: "due-dates", label: "Due dates", path: "specs/due-dates/prd.md" }],
        }}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Due dates/ }));
    expect(onSelect).toHaveBeenCalledWith("due-dates");
  });
});
