import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { DraftPreview, splitSections } from "@/components/ceremony/guided";
import type { SectionProvenanceEntry } from "@/lib/graphql/queries/authoring";

const CONTENT = [
  "# PRD: Due dates for tasks",
  "",
  "## Summary",
  "",
  "This PRD defines due dates.",
  "",
  "## Problem & Evidence",
  "",
  "Team leads cannot see overdue work.",
  "",
].join("\n");

const SECTIONS: SectionProvenanceEntry[] = [
  { title: "Summary", question_ids: ["P-Q1"], coverage_ids: ["P-Q1"], state: "provisional" },
  {
    title: "Problem & Evidence",
    question_ids: ["P-Q1"],
    coverage_ids: ["P-Q1"],
    state: "provisional",
  },
];

describe("splitSections", () => {
  it("splits on generated headings and attaches helper provenance", () => {
    const { header, rendered } = splitSections(CONTENT, SECTIONS);

    expect(header).toContain("# PRD: Due dates for tasks");
    expect(rendered.map((section) => section.title)).toEqual([
      "Summary",
      "Problem & Evidence",
    ]);
    expect(rendered[0].provenance?.question_ids).toEqual(["P-Q1"]);
  });

  it("leaves provenance null for a section the helper did not declare", () => {
    const { rendered } = splitSections(CONTENT, [SECTIONS[0]]);
    expect(rendered[1].provenance).toBeNull();
  });
});

describe("DraftPreview", () => {
  it("shows the revision and each section's source question", () => {
    render(
      <DraftPreview
        content={CONTENT}
        sections={SECTIONS}
        artifactPath="specs/due-dates/prd.md"
        revision={2}
        onEditSection={vi.fn()}
      />,
    );

    expect(screen.getByText("PRD · rev 2")).toBeInTheDocument();
    expect(screen.getAllByText("P-Q1").length).toBe(2);
  });

  it("edits a section through its source question, not the prose", () => {
    const onEditSection = vi.fn();
    render(
      <DraftPreview
        content={CONTENT}
        sections={SECTIONS}
        artifactPath="specs/due-dates/prd.md"
        revision={2}
        onEditSection={onEditSection}
      />,
    );

    const editButtons = screen.getAllByRole("button", { name: /Edit the answer behind/ });
    fireEvent.click(editButtons[0]);
    expect(onEditSection).toHaveBeenCalledWith("P-Q1");
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });
});
