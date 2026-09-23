import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, within } from "@testing-library/react";
import { baseDigest, partialDigest } from "./fixtures";
import { setupUrqlHooks as sharedSetupUrqlHooks, renderDigestPage, type UrqlHookOverrides } from "./testUtils";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/digest/workflows",
}));

vi.mock("urql", () => ({
  useQuery: vi.fn(),
  useMutation: vi.fn(),
  useSubscription: vi.fn(),
  gql: (strings: TemplateStringsArray) => strings.raw.join(""),
}));

import { useQuery, useMutation, useSubscription } from "urql";
import DigestWorkflowsPage from "@/app/digest/workflows/page";

const mockedUseQuery = vi.mocked(useQuery);
const mockedUseMutation = vi.mocked(useMutation);
const mockedUseSubscription = vi.mocked(useSubscription);

function setupUrqlHooks(overrides: UrqlHookOverrides = {}) {
  return sharedSetupUrqlHooks(mockedUseQuery, mockedUseMutation, mockedUseSubscription, overrides);
}

describe("DigestWorkflowsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows a loading skeleton while fetching", () => {
    setupUrqlHooks({ digest: null, fetching: true, status: null });
    const { container } = renderDigestPage(<DigestWorkflowsPage />);
    expect(container.querySelector(".digest-kpi-grid")).toBeTruthy();
  });

  it("shows a GraphQL error state", () => {
    setupUrqlHooks({ digest: null, error: new Error("network unreachable") });
    renderDigestPage(<DigestWorkflowsPage />);
    expect(screen.getByText("Digest could not be read")).toBeInTheDocument();
  });

  it("shows the empty state when the project map has no indexed files", () => {
    setupUrqlHooks({ digest: { ...baseDigest, footprint: { ...baseDigest.footprint, fileCount: 0 } } });
    renderDigestPage(<DigestWorkflowsPage />);
    expect(screen.getByText(/Commands will populate once the repository has content/)).toBeInTheDocument();
  });

  it("shows the no-commands empty state for a partial digest", () => {
    setupUrqlHooks({ digest: partialDigest });
    renderDigestPage(<DigestWorkflowsPage />);
    expect(screen.getByText("No commands discovered in CLAUDE.md, AGENTS.md, or project manifests.")).toBeInTheDocument();
    expect(screen.getByText("No test commands discovered in CLAUDE.md, AGENTS.md, or project manifests.")).toBeInTheDocument();
  });

  it("groups commands by working directory", () => {
    setupUrqlHooks({ digest: baseDigest });
    renderDigestPage(<DigestWorkflowsPage />);
    // baseDigest has one command in "." and two in "dashboard/frontend" —
    // "." and "dashboard/frontend" each appear twice (grouped list +
    // test-suite table both key off workingDirectory), so scope to the
    // grouped-commands panel specifically.
    const grouped = screen.getByText("Commands by working directory").closest(".surface") as HTMLElement;
    expect(within(grouped).getByText(".")).toBeInTheDocument();
    expect(within(grouped).getByText("dashboard/frontend")).toBeInTheDocument();
    expect(within(grouped).getByText("pytest tests/")).toBeInTheDocument();
    // BUILD purpose only ever appears in the grouped list, never the
    // test-suite table, so this one is safe unscoped.
    expect(screen.getByText("npm run build")).toBeInTheDocument();
  });

  it("derives a test-suite table from TEST-purpose commands, with an honestly-derived framework label", () => {
    setupUrqlHooks({ digest: baseDigest });
    renderDigestPage(<DigestWorkflowsPage />);
    expect(screen.getByText("Discovered test suites")).toBeInTheDocument();
    expect(screen.getByText("pytest")).toBeInTheDocument(); // detected from "pytest tests/"
    // the BUILD command must not appear in the test-suite table
    const suiteSection = screen.getByText("Discovered test suites").closest(".surface");
    expect(suiteSection).not.toBeNull();
    expect(suiteSection!.textContent).not.toContain("npm run build");
  });

  it("never fabricates a file-count column for the derived test-suite table", () => {
    setupUrqlHooks({ digest: baseDigest });
    renderDigestPage(<DigestWorkflowsPage />);
    expect(screen.queryByText(/files?$/i, { selector: "th" })).not.toBeInTheDocument();
  });
});
