import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { DraftsInProgress } from "@/components/ceremony/guided";
import type { AuthoringSessionSummary } from "@/lib/graphql/queries/authoring";

function session(over: Partial<AuthoringSessionSummary> = {}): AuthoringSessionSummary {
  return {
    featureName: "task-due-dates",
    featureTitle: "Due dates for tasks",
    artifactType: "prd",
    status: "question",
    revision: 3,
    updatedAt: "2026-09-04T05:37:53.876893+00:00",
    progress: { confirmed: 1, total: 3, deferred: [] },
    draftAvailable: true,
    artifactPath: "specs/task-due-dates/prd.md",
    authoringUrl: null,
    message: "Answer the current clarification.",
    ...over,
  };
}

describe("DraftsInProgress", () => {
  it("renders nothing when no interview has been started", () => {
    const { container } = render(<DraftsInProgress sessions={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("links an in-progress interview to its authoring route", () => {
    render(<DraftsInProgress sessions={[session()]} />);

    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", "/define/task-due-dates/authoring/prd");
    expect(link).toHaveTextContent("Due dates for tasks");
    expect(link).toHaveTextContent("1/3 confirmed");
    expect(link).toHaveTextContent("Resume");
    expect(screen.getByText(/task-due-dates · rev 3/)).toBeInTheDocument();
  });

  it("counts the sessions in its heading", () => {
    render(
      <DraftsInProgress
        sessions={[session(), session({ featureName: "reopen-task", revision: 0 })]}
      />,
    );
    expect(screen.getByText(/Guided drafts · 2/)).toBeInTheDocument();
  });

  it("offers a finished draft for opening rather than resuming", () => {
    render(<DraftsInProgress sessions={[session({ status: "drafted" })]} />);

    expect(screen.getByRole("link")).toHaveTextContent("Open");
    expect(screen.getByText("Drafted")).toBeInTheDocument();
  });

  it("shows an unreadable checkpoint without offering to open it", () => {
    render(
      <DraftsInProgress
        sessions={[session({ status: "error", revision: null, message: "unreadable" })]}
      />,
    );

    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByText("Checkpoint unreadable")).toBeInTheDocument();
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
  });

  it("names the status the helper reported, even an unmapped one", () => {
    render(<DraftsInProgress sessions={[session({ status: "interviewing" })]} />);
    expect(screen.getByText("Interviewing")).toBeInTheDocument();
  });
});
