import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CoverageEditCard } from "@/components/ceremony/guided";

describe("CoverageEditCard", () => {
  it("does not revise a PRD until the author enters and confirms a replacement", () => {
    const onSubmit = vi.fn();
    render(
      <CoverageEditCard
        questionId="P-Q1"
        submitting={false}
        onCancel={vi.fn()}
        onSubmit={onSubmit}
      />,
    );

    const submit = screen.getByRole("button", { name: "Update PRD" });
    expect(submit).toBeDisabled();
    expect(onSubmit).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("Replacement answer"), {
      target: { value: "Updated problem evidence from the author." },
    });
    fireEvent.click(submit);

    expect(onSubmit).toHaveBeenCalledWith("Updated problem evidence from the author.");
  });

  it("allows the author to cancel without changing the PRD", () => {
    const onCancel = vi.fn();
    const onSubmit = vi.fn();
    render(
      <CoverageEditCard
        questionId="P-Q8"
        submitting={false}
        onCancel={onCancel}
        onSubmit={onSubmit}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledOnce();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("prefills the confirmed answer being revised", () => {
    render(
      <CoverageEditCard
        questionId="P-Q2"
        initialAnswer="Every task user needs due dates."
        submitting={false}
        onCancel={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );

    expect(screen.getByLabelText("Replacement answer")).toHaveValue(
      "Every task user needs due dates.",
    );
    expect(screen.getByRole("button", { name: "Update PRD" })).toBeEnabled();
  });
});
