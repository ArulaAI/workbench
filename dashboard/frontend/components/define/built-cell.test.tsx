import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { BuiltCell } from "@/components/define/built-cell";

const baseBuilt = {
  coveragePct: 85,
  criteriaPassed: 17,
  criteriaTotal: 20,
  guardianVerdict: "All checks pass",
  taskProgress: 100,
  tasksDone: 8,
  tasksTotal: 8,
  blockedCount: 0,
  completedAt: "2025-01-15",
};

describe("BuiltCell — complete state", () => {
  it("renders coverage percentage", () => {
    render(<BuiltCell state="complete" built={baseBuilt} />);
    expect(screen.getByText("85%")).toBeInTheDocument();
  });

  it("renders criteria fraction", () => {
    render(<BuiltCell state="complete" built={baseBuilt} />);
    expect(screen.getByText("17/20")).toBeInTheDocument();
  });

  it("renders guardian verdict", () => {
    render(<BuiltCell state="complete" built={baseBuilt} />);
    expect(screen.getByText("All checks pass")).toBeInTheDocument();
  });

  it("renders completedAt date", () => {
    render(<BuiltCell state="complete" built={baseBuilt} />);
    expect(screen.getByText("2025-01-15")).toBeInTheDocument();
  });

  it("omits guardian verdict when null", () => {
    render(<BuiltCell state="complete" built={{ ...baseBuilt, guardianVerdict: null }} />);
    expect(screen.queryByText("All checks pass")).not.toBeInTheDocument();
  });
});

describe("BuiltCell — executing state", () => {
  const executingBuilt = {
    ...baseBuilt,
    coveragePct: 40,
    tasksDone: 3,
    tasksTotal: 10,
    blockedCount: 0,
    taskProgress: 30,
  };

  it("renders task count", () => {
    render(<BuiltCell state="executing" built={executingBuilt} />);
    expect(screen.getByText("3/10 tasks")).toBeInTheDocument();
  });

  it("does not show blocked count when zero", () => {
    render(<BuiltCell state="executing" built={executingBuilt} />);
    expect(screen.queryByText(/blocked/)).not.toBeInTheDocument();
  });

  it("shows blocked count in red when greater than zero", () => {
    render(
      <BuiltCell state="executing" built={{ ...executingBuilt, blockedCount: 2 }} />,
    );
    const blockedEl = screen.getByText("2 blocked");
    expect(blockedEl).toBeInTheDocument();
    expect(blockedEl.style.color).toBe("var(--color-red)");
  });
});

describe("BuiltCell — writing state", () => {
  it("renders italic placeholder text", () => {
    render(<BuiltCell state="writing" built={baseBuilt} />);
    expect(screen.getByText("Specs in progress")).toBeInTheDocument();
  });
});

describe("BuiltCell — unplanned state", () => {
  it("renders italic placeholder text", () => {
    render(<BuiltCell state="unplanned" built={baseBuilt} />);
    expect(screen.getByText("Not yet planned")).toBeInTheDocument();
  });
});
