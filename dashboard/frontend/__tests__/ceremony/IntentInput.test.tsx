import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import type { OperationResult } from "urql";

const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));

// Capture the subscription handler so tests can push events into it
let subscriptionHandler: ((prev: unknown, data: unknown) => unknown) | null = null;
let subscriptionArgs: { variables?: Record<string, unknown>; pause?: boolean } | null = null;

vi.mock("urql", () => ({
  useQuery: vi.fn(),
  useMutation: vi.fn(),
  useSubscription: vi.fn(),
  gql: (strings: TemplateStringsArray) => strings.raw.join(""),
}));

import { IntentInput } from "@/components/ceremony/IntentInput";
import { useQuery, useMutation, useSubscription } from "urql";

const mockedUseQuery = vi.mocked(useQuery);
const mockedUseMutation = vi.mocked(useMutation);
const mockedUseSubscription = vi.mocked(useSubscription);

const MODELS = [
  { id: "ollama/mistral:latest", provider: "ollama", label: "Ollama: mistral:latest" },
];

let executeDeclare: ReturnType<typeof vi.fn>;

function setupMocks() {
  executeDeclare = vi.fn().mockResolvedValue({
    data: {
      declareIntent: {
        featureName: "test-feature",
        contextPackage: { intent: "test" },
        ceremony: null,
      },
    },
  } as Partial<OperationResult>);

  mockedUseQuery.mockReturnValue([
    { data: { ceremonyModels: MODELS }, fetching: false, error: undefined, stale: false, extensions: undefined } as any,
    vi.fn(),
  ] as any);

  mockedUseMutation.mockReturnValue([
    { fetching: false, stale: false, error: undefined, extensions: undefined, data: undefined } as any,
    executeDeclare,
  ] as any);

  mockedUseSubscription.mockImplementation((args: any, handler: any) => {
    subscriptionArgs = args;
    subscriptionHandler = handler;
    return [{ data: undefined, error: undefined, fetching: false, stale: false, extensions: undefined } as any, vi.fn()] as any;
  });
}

describe("IntentInput", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    subscriptionHandler = null;
    subscriptionArgs = null;
    setupMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("subscription is not paused when feature name is entered", () => {
    render(<IntentInput />);

    const nameInput = screen.getByPlaceholderText("feature-name");
    fireEvent.change(nameInput, { target: { value: "my-feature" } });

    // useSubscription is called on every render — find the last call
    const lastCall = mockedUseSubscription.mock.calls.at(-1);
    expect(lastCall).toBeDefined();
    expect(lastCall![0].pause).toBe(false);
    expect(lastCall![0].variables.feature).toBe("my-feature");
  });

  it("subscription is paused when feature name is empty", () => {
    render(<IntentInput />);

    const lastCall = mockedUseSubscription.mock.calls.at(-1);
    expect(lastCall![0].pause).toBe(true);
  });

  it("shows progress indicators when submitting", async () => {
    render(<IntentInput />);

    const nameInput = screen.getByPlaceholderText("feature-name");
    const intentInput = screen.getByPlaceholderText("What do you want to build?");

    await act(async () => {
      fireEvent.change(nameInput, { target: { value: "test-feature" } });
      fireEvent.change(intentInput, { target: { value: "Build a recall surface for the dashboard" } });
    });

    const submitButton = screen.getByText("Deliver Context");
    await act(async () => {
      fireEvent.click(submitButton);
    });

    // Sources should be visible in pending state
    expect(screen.getByText("Semantic graph")).toBeInTheDocument();
    expect(screen.getByText("Learnings")).toBeInTheDocument();
    expect(screen.getByText("Defects")).toBeInTheDocument();
  });

  it("updates source states when subscription delivers events before mutation resolves", async () => {
    // Make the mutation hang so subscription events arrive first
    let resolveMutation: (val: any) => void;
    executeDeclare.mockReturnValue(new Promise((resolve) => { resolveMutation = resolve; }));

    render(<IntentInput />);

    const nameInput = screen.getByPlaceholderText("feature-name");
    const intentInput = screen.getByPlaceholderText("What do you want to build?");

    await act(async () => {
      fireEvent.change(nameInput, { target: { value: "test-feature" } });
      fireEvent.change(intentInput, { target: { value: "Build a recall surface for the dashboard" } });
    });

    const submitButton = screen.getByText("Deliver Context");
    await act(async () => {
      fireEvent.click(submitButton);
    });

    // Mutation is still pending. Deliver subscription events.
    expect(subscriptionHandler).not.toBeNull();
    act(() => {
      subscriptionHandler!(undefined, {
        contextAssemblyProgress: {
          feature: "test-feature",
          source: "codebase",
          status: "ok",
          error: null,
        },
      });
    });

    // Only codebase should have a checkmark, not all sources
    const checkmarks = screen.getAllByText("✓");
    expect(checkmarks).toHaveLength(1);

    // Semantic graph (codebase) should be green
    const codebaseItem = screen.getByText("Semantic graph").closest("div");
    expect(codebaseItem!.style.color).toContain("accent");

    // Learnings should still be pending (tertiary)
    const learningsItem = screen.getByText("Learnings").closest("div");
    expect(learningsItem!.style.color).toContain("tertiary");

    // Now resolve the mutation
    await act(async () => {
      resolveMutation!({ data: { declareIntent: { featureName: "test-feature", contextPackage: { intent: "test" }, ceremony: null } } });
    });
  });

  it("navigates after 'complete' event from subscription", async () => {
    const onDeclared = vi.fn();
    render(<IntentInput onDeclared={onDeclared} />);

    const nameInput = screen.getByPlaceholderText("feature-name");
    const intentInput = screen.getByPlaceholderText("What do you want to build?");

    await act(async () => {
      fireEvent.change(nameInput, { target: { value: "test-feature" } });
      fireEvent.change(intentInput, { target: { value: "Build a recall surface for the dashboard" } });
    });

    const submitButton = screen.getByText("Deliver Context");
    await act(async () => {
      fireEvent.click(submitButton);
    });

    // Simulate subscription delivering source events then complete
    act(() => {
      for (const source of ["codebase", "learnings", "defects", "project_knowledge", "vision", "related_features", "audit_history"]) {
        subscriptionHandler!(undefined, {
          contextAssemblyProgress: {
            feature: "test-feature",
            source,
            status: "ok",
            error: null,
          },
        });
      }
      subscriptionHandler!(undefined, {
        contextAssemblyProgress: {
          feature: "test-feature",
          source: "complete",
          status: "ok",
          error: null,
        },
      });
    });

    // Navigation happens after 300ms timeout
    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(onDeclared).toHaveBeenCalledWith("test-feature");
    expect(mockPush).toHaveBeenCalledWith("/define/test-feature");
  });

  it("does not navigate when mutation returns — waits for subscription complete", async () => {
    render(<IntentInput />);

    const nameInput = screen.getByPlaceholderText("feature-name");
    const intentInput = screen.getByPlaceholderText("What do you want to build?");

    await act(async () => {
      fireEvent.change(nameInput, { target: { value: "test-feature" } });
      fireEvent.change(intentInput, { target: { value: "Build a recall surface for the dashboard" } });
    });

    const submitButton = screen.getByText("Deliver Context");
    await act(async () => {
      fireEvent.click(submitButton);
    });

    // Mutation resolved but no subscription events yet — should NOT navigate
    act(() => {
      vi.advanceTimersByTime(1000);
    });

    expect(mockPush).not.toHaveBeenCalled();
  });

  it("auto-selects first ceremony model", () => {
    render(<IntentInput />);

    // The model select should exist and have the first model selected
    const select = screen.getByLabelText("LLM model for scoping");
    expect(select).toBeInTheDocument();
    expect((select as HTMLSelectElement).value).toBe("ollama/mistral:latest");
  });
});
