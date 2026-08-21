import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { DefectRow } from "@/components/define/defect-row";

const baseDefect = {
  name: "Login button unresponsive on Safari",
  severity: "P1",
  status: "Open",
  description: "Clicking the login button on Safari 17 produces no response.",
  impact: "Blocks all Safari users from authenticating.",
  filedAt: null,
};

describe("DefectRow", () => {
  it("renders the severity badge", () => {
    render(<DefectRow defect={baseDefect} />);
    expect(screen.getByText("P1")).toBeInTheDocument();
  });

  it("renders the defect name", () => {
    render(<DefectRow defect={baseDefect} />);
    expect(
      screen.getByText("Login button unresponsive on Safari"),
    ).toBeInTheDocument();
  });

  it("truncates names longer than 40 characters", () => {
    const defect = {
      ...baseDefect,
      name: "This is a very long defect name that exceeds forty characters",
    };
    render(<DefectRow defect={defect} />);
    expect(
      screen.getByText("This is a very long defect name that exc\u2026"),
    ).toBeInTheDocument();
  });

  it("does not truncate names at or under 40 characters", () => {
    const defect = { ...baseDefect, name: "Exactly forty characters long name!!!!!" };
    render(<DefectRow defect={defect} />);
    expect(
      screen.getByText("Exactly forty characters long name!!!!!"),
    ).toBeInTheDocument();
  });

  it("renders the status text", () => {
    render(<DefectRow defect={baseDefect} />);
    expect(screen.getByText("Open")).toBeInTheDocument();
  });

  it("renders the description", () => {
    render(<DefectRow defect={baseDefect} />);
    expect(
      screen.getByText(
        "Clicking the login button on Safari 17 produces no response.",
      ),
    ).toBeInTheDocument();
  });

  it("renders impact text when provided", () => {
    render(<DefectRow defect={baseDefect} />);
    expect(
      screen.getByText("Blocks all Safari users from authenticating."),
    ).toBeInTheDocument();
  });

  it("renders em-dash when impact is null", () => {
    const defect = { ...baseDefect, impact: null };
    render(<DefectRow defect={defect} />);
    expect(screen.getByText("\u2014")).toBeInTheDocument();
  });

  it("applies 0.45 opacity for P3 severity", () => {
    const defect = { ...baseDefect, severity: "P3" };
    const { container } = render(<DefectRow defect={defect} />);
    const row = container.firstChild as HTMLElement;
    expect(row.style.opacity).toBe("0.45");
  });

  it("does not apply reduced opacity for P0 severity", () => {
    const defect = { ...baseDefect, severity: "P0" };
    const { container } = render(<DefectRow defect={defect} />);
    const row = container.firstChild as HTMLElement;
    expect(row.style.opacity).not.toBe("0.45");
  });
});
