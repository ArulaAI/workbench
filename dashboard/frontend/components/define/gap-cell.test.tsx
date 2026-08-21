import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { GapCell } from "@/components/define/gap-cell";

const baseGap = {
  escalationCount: 0,
  escalations: [],
  unverifiableCount: 0,
  reworkCount: 0,
};

describe("GapCell — writing state", () => {
  it("renders an empty cell", () => {
    const { container } = render(<GapCell state="writing" gap={baseGap} />);
    expect(container.firstChild).toBeEmptyDOMElement();
  });
});

describe("GapCell — unplanned state", () => {
  it("renders italic placeholder", () => {
    render(<GapCell state="unplanned" gap={baseGap} />);
    expect(screen.getByText("Requires execution data")).toBeInTheDocument();
  });
});

describe("GapCell — complete state", () => {
  it("renders escalation count label", () => {
    const gap = {
      ...baseGap,
      escalationCount: 2,
      escalations: [
        { description: "Missing retry logic", linkedWarningId: null },
        { description: "Auth bypass on admin route", linkedWarningId: "w-1" },
      ],
    };
    render(<GapCell state="complete" gap={gap} />);
    expect(screen.getByText("2 escalations")).toBeInTheDocument();
  });

  it("renders escalation description text", () => {
    const gap = {
      ...baseGap,
      escalationCount: 1,
      escalations: [
        { description: "Missing retry logic", linkedWarningId: null },
      ],
    };
    render(<GapCell state="complete" gap={gap} />);
    expect(screen.getByText("Missing retry logic")).toBeInTheDocument();
  });

  it("renders RefMarker for escalation with linkedWarningId", () => {
    const gap = {
      ...baseGap,
      escalationCount: 1,
      escalations: [
        { description: "Auth bypass on admin route", linkedWarningId: "w-1" },
      ],
    };
    render(<GapCell state="complete" gap={gap} />);
    expect(screen.getByRole("img")).toBeInTheDocument();
  });

  it("does not render RefMarker when linkedWarningId is null", () => {
    const gap = {
      ...baseGap,
      escalationCount: 1,
      escalations: [
        { description: "Missing retry logic", linkedWarningId: null },
      ],
    };
    render(<GapCell state="complete" gap={gap} />);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("renders unverifiable count", () => {
    render(<GapCell state="complete" gap={{ ...baseGap, unverifiableCount: 3 }} />);
    expect(screen.getByText("3 unverifiable")).toBeInTheDocument();
  });

  it("renders rework count", () => {
    render(<GapCell state="complete" gap={{ ...baseGap, reworkCount: 1 }} />);
    expect(screen.getByText("1 rework")).toBeInTheDocument();
  });

  it("renders singular 'escalation' label for count of 1", () => {
    const gap = {
      ...baseGap,
      escalationCount: 1,
      escalations: [{ description: "Issue", linkedWarningId: null }],
    };
    render(<GapCell state="complete" gap={gap} />);
    expect(screen.getByText("1 escalation")).toBeInTheDocument();
  });
});
