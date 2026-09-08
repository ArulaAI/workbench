import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
      />,
    );

    expect(screen.getByText("PRD · rev 2")).toBeInTheDocument();
    expect(screen.getAllByText("From P-Q1").length).toBe(2);
  });

  it("keeps provenance without exposing source-answer editing", () => {
    render(
      <DraftPreview
        content={CONTENT}
        sections={SECTIONS}
        artifactPath="specs/due-dates/prd.md"
        revision={2}
        onEditDraftSection={vi.fn()}
      />,
    );

    expect(screen.queryByText("Edit answer")).not.toBeInTheDocument();
    expect(screen.getAllByText("Edit draft")).toHaveLength(2);
    expect(screen.getAllByText("From P-Q1")).toHaveLength(2);
  });

  it("edits a draft section directly and saves the section body", async () => {
    const onEditDraftSection = vi.fn().mockResolvedValue(true);
    render(
      <DraftPreview
        content={CONTENT}
        sections={SECTIONS}
        artifactPath="specs/due-dates/prd.md"
        revision={2}
        onEditDraftSection={onEditDraftSection}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Edit Summary directly in the draft" }),
    );
    const editor = screen.getByRole("textbox", { name: "Edit Summary draft content" });
    fireEvent.change(editor, { target: { value: "A manually refined summary." } });
    fireEvent.click(screen.getByRole("button", { name: "Save section" }));

    await waitFor(() =>
      expect(onEditDraftSection).toHaveBeenCalledWith(
        "Summary",
        "A manually refined summary.",
      ),
    );
    await waitFor(() =>
      expect(screen.queryByRole("textbox", { name: "Edit Summary draft content" })).not.toBeInTheDocument(),
    );
  });

  it("collects a section comment without regenerating immediately", () => {
    const onAddComment = vi.fn();
    render(
      <DraftPreview
        content={CONTENT}
        sections={SECTIONS}
        artifactPath="specs/due-dates/prd.md"
        revision={2}
        onAddComment={onAddComment}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Add a review comment to Summary" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Review comment for Summary" }), {
      target: { value: "Mention the 30-day baseline." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add to review" }));

    expect(onAddComment).toHaveBeenCalledWith("Summary", "Mention the 30-day baseline.");
  });

  it("labels a model-reconsidered section as review regenerated", () => {
    render(
      <DraftPreview
        content={CONTENT}
        sections={[
          { ...SECTIONS[0], state: "reviewed" },
          SECTIONS[1],
        ]}
        artifactPath="specs/due-dates/prd.md"
        revision={3}
      />,
    );

    expect(screen.getByText("Review regenerated · From P-Q1")).toBeInTheDocument();
    expect(screen.queryByText("Manual edit")).not.toBeInTheDocument();
  });

  it("embeds a simple editor with versions, counts, and formatting controls", () => {
    const onReviewCommit = vi.fn();
    render(
      <DraftPreview
        content={CONTENT}
        sections={SECTIONS}
        artifactPath="specs/due-dates/prd.md"
        revision={3}
        versions={[
          { revision: 2, content: CONTENT.replace("defines", "introduced") },
          { revision: 3, content: CONTENT },
        ]}
        onSaveDocument={vi.fn().mockResolvedValue(true)}
        onReviewCommit={onReviewCommit}
      />,
    );

    expect(screen.getByRole("combobox", { name: "Document version" })).toHaveValue("3");
    expect(screen.getByText("PRD · v2 (Draft)")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Current draft · v2" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Bold" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Table" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Review & commit" })).toBeInTheDocument();
    expect(screen.getByText(/words · .*characters/)).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "PRD: Due dates for tasks" }).closest(
        '[data-document-scroll="true"]',
      ),
    ).not.toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "View rendered Markdown" }));
    expect(screen.getByRole("button", { name: "Edit Markdown" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Summary", level: 2 })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Bold" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Review & commit" }));
    expect(onReviewCommit).toHaveBeenCalledOnce();
  });

  it("publishes a clean draft and labels immutable versions", async () => {
    const onPublish = vi.fn().mockResolvedValue(true);
    render(
      <DraftPreview
        content={CONTENT}
        sections={SECTIONS}
        artifactPath="specs/due-dates/design.md"
        artifactType="design"
        artifactLabel="Design"
        revision={4}
        publishedRevision={3}
        versions={[
          { revision: 3, content: CONTENT, status: "published" },
          { revision: 4, content: CONTENT, status: "draft" },
        ]}
        onSaveDocument={vi.fn().mockResolvedValue(true)}
        onPublish={onPublish}
      />,
    );

    expect(screen.getByText("Design · v2 (Draft)")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Published · v1" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Publish" }));
    await waitFor(() => expect(onPublish).toHaveBeenCalledOnce());

    fireEvent.change(screen.getByRole("combobox", { name: "Document version" }), {
      target: { value: "3" },
    });
    expect(screen.getByText("Design · v1 (Published history)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Published history" })).toBeDisabled();
  });

  it("does not treat a comment-only session revision as a new document version", () => {
    render(
      <DraftPreview
        content={CONTENT}
        sections={SECTIONS}
        artifactPath="specs/due-dates/prd.md"
        revision={8}
        publishedRevision={7}
        versions={[
          { revision: 6, content: CONTENT, status: "draft" },
          { revision: 7, content: CONTENT, status: "published" },
        ]}
        onSaveDocument={vi.fn().mockResolvedValue(true)}
        onPublish={vi.fn().mockResolvedValue(true)}
      />,
    );

    expect(screen.getByRole("combobox", { name: "Document version" })).toHaveValue("7");
    expect(screen.getByText("PRD · v2 (Published)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Published" })).toBeDisabled();
  });
});
