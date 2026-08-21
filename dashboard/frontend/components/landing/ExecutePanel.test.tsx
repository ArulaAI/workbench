import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ExecutePanel } from "@/components/landing/ExecutePanel";
import type { ExecutePanel as ExecutePanelData } from "@/lib/graphql/queries/landing";

const baseExecute: ExecutePanelData = {
  runningFeatures: [],
  escalations: [],
};

const mockOnRespond = vi.fn().mockResolvedValue(undefined);

describe("ExecutePanel", () => {
  beforeEach(() => {
    mockOnRespond.mockClear();
  });

  it("renders empty state when runningFeatures is empty", () => {
    render(<ExecutePanel execute={baseExecute} onRespondToEscalation={mockOnRespond} />);
    expect(screen.getByText("No features running.")).toBeInTheDocument();
  });

  it("renders running features with name and progress percentage", () => {
    const execute: ExecutePanelData = {
      ...baseExecute,
      runningFeatures: [
        { name: "Auth feature", progressPct: 65, tasksCompleted: 13, tasksTotal: 20, blockedCount: 0 },
      ],
    };
    render(<ExecutePanel execute={execute} onRespondToEscalation={mockOnRespond} />);
    expect(screen.getByText("Auth feature")).toBeInTheDocument();
    expect(screen.getByText("65%")).toBeInTheDocument();
  });

  it("renders blocked count badge when blockedCount > 0", () => {
    const execute: ExecutePanelData = {
      ...baseExecute,
      runningFeatures: [
        { name: "Auth feature", progressPct: 40, tasksCompleted: 8, tasksTotal: 20, blockedCount: 2 },
      ],
    };
    render(<ExecutePanel execute={execute} onRespondToEscalation={mockOnRespond} />);
    expect(screen.getByText("2 blocked")).toBeInTheDocument();
  });

  it("does not render blocked badge when blockedCount is 0", () => {
    const execute: ExecutePanelData = {
      ...baseExecute,
      runningFeatures: [
        { name: "Auth feature", progressPct: 40, tasksCompleted: 8, tasksTotal: 20, blockedCount: 0 },
      ],
    };
    render(<ExecutePanel execute={execute} onRespondToEscalation={mockOnRespond} />);
    expect(screen.queryByText(/blocked/)).not.toBeInTheDocument();
  });

  it("renders escalation question text and input field", () => {
    const execute: ExecutePanelData = {
      ...baseExecute,
      escalations: [
        { feature: "auth", taskId: "task-1", taskTitle: "Setup auth", question: "Should we use OAuth?" },
      ],
    };
    render(<ExecutePanel execute={execute} onRespondToEscalation={mockOnRespond} />);
    expect(screen.getByText("Should we use OAuth?")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Your response…")).toBeInTheDocument();
  });

  it("calls onRespondToEscalation with correct args and clears input on send", async () => {
    const execute: ExecutePanelData = {
      ...baseExecute,
      escalations: [
        { feature: "auth", taskId: "task-1", taskTitle: "Setup auth", question: "Should we use OAuth?" },
      ],
    };
    render(<ExecutePanel execute={execute} onRespondToEscalation={mockOnRespond} />);

    const input = screen.getByPlaceholderText("Your response…");
    fireEvent.change(input, { target: { value: "Yes, use OAuth" } });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));

    await waitFor(() => {
      expect(mockOnRespond).toHaveBeenCalledWith("auth", "task-1", "Yes, use OAuth");
    });
    await waitFor(() => {
      expect(input).toHaveValue("");
    });
  });

  it("disables Send button during in-flight mutation", async () => {
    let resolvePromise!: () => void;
    const pendingPromise = new Promise<void>((resolve) => {
      resolvePromise = resolve;
    });
    const slowRespond = vi.fn().mockReturnValue(pendingPromise);

    const execute: ExecutePanelData = {
      ...baseExecute,
      escalations: [
        { feature: "auth", taskId: "task-1", taskTitle: "Setup auth", question: "Should we use OAuth?" },
      ],
    };
    render(<ExecutePanel execute={execute} onRespondToEscalation={slowRespond} />);

    const input = screen.getByPlaceholderText("Your response…");
    fireEvent.change(input, { target: { value: "Yes" } });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /sending/i })).toBeDisabled();
    });

    resolvePromise();
  });

  it("applies .surface class to the card container", () => {
    const { container } = render(
      <ExecutePanel execute={baseExecute} onRespondToEscalation={mockOnRespond} />,
    );
    expect(container.firstChild).toHaveClass("surface");
  });
});
