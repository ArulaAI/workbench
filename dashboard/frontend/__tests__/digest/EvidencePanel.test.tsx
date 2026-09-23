import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { EvidenceAffordance } from "@/components/digest/EvidencePanel";
import type { DigestEvidence } from "@/lib/graphql/queries/repository-digest";

const evidence: DigestEvidence[] = [
  { source: "manifest", path: "package.json", line: null, symbol: null, artifactKey: null, description: "scripts.dev" },
  { source: "semantic_graph", path: "lib/a.py", line: 10, symbol: "lib/a.py::Foo", artifactKey: null, description: "Representative symbol" },
];

describe("EvidenceAffordance", () => {
  it("renders nothing when there is no evidence", () => {
    const { container } = render(<EvidenceAffordance evidence={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("opens a labelled modal dialog with a close button", () => {
    render(<EvidenceAffordance evidence={evidence} />);
    fireEvent.click(screen.getByRole("button", { name: "2 sources" }));

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    const labelId = dialog.getAttribute("aria-labelledby");
    expect(labelId).toBeTruthy();
    expect(document.getElementById(labelId!)).toHaveTextContent("Evidence");
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
  });

  it("moves focus into the panel (to the close button) when opened", () => {
    render(<EvidenceAffordance evidence={evidence} />);
    fireEvent.click(screen.getByRole("button", { name: "2 sources" }));
    expect(screen.getByRole("button", { name: "Close" })).toHaveFocus();
  });

  it("restores focus to the trigger button when closed via the close button", () => {
    render(<EvidenceAffordance evidence={evidence} />);
    const trigger = screen.getByRole("button", { name: "2 sources" });
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("closes on Escape and restores focus to the trigger", () => {
    render(<EvidenceAffordance evidence={evidence} />);
    const trigger = screen.getByRole("button", { name: "2 sources" });
    fireEvent.click(trigger);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("closes when the scrim is clicked", () => {
    const { container } = render(<EvidenceAffordance evidence={evidence} />);
    fireEvent.click(screen.getByRole("button", { name: "2 sources" }));
    fireEvent.click(container.querySelector(".digest-evidence-scrim")!);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("traps Tab focus within the panel", () => {
    render(<EvidenceAffordance evidence={evidence} />);
    fireEvent.click(screen.getByRole("button", { name: "2 sources" }));

    const dialog = screen.getByRole("dialog");
    const focusable = dialog.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled])'
    );
    const last = focusable[focusable.length - 1];
    last.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(screen.getByRole("button", { name: "Close" })).toHaveFocus();
  });

  it("still shows the trigger's aria-expanded state", () => {
    render(<EvidenceAffordance evidence={evidence} />);
    const trigger = screen.getByRole("button", { name: "2 sources" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
  });
});
