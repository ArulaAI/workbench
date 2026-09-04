import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import { baseDigest, partialDigest } from "./fixtures";
import { setupUrqlHooks as sharedSetupUrqlHooks, renderDigestPage, type UrqlHookOverrides } from "./testUtils";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/digest/coverage",
}));

vi.mock("urql", () => ({
  useQuery: vi.fn(),
  useMutation: vi.fn(),
  useSubscription: vi.fn(),
  gql: (strings: TemplateStringsArray) => strings.raw.join(""),
}));

import { useQuery, useMutation, useSubscription } from "urql";
import DigestCoveragePage from "@/app/digest/coverage/page";

const mockedUseQuery = vi.mocked(useQuery);
const mockedUseMutation = vi.mocked(useMutation);
const mockedUseSubscription = vi.mocked(useSubscription);

function setupUrqlHooks(overrides: UrqlHookOverrides = {}) {
  return sharedSetupUrqlHooks(mockedUseQuery, mockedUseMutation, mockedUseSubscription, overrides);
}

describe("DigestCoveragePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows a loading skeleton while fetching", () => {
    setupUrqlHooks({ digest: null, fetching: true, status: null });
    const { container } = renderDigestPage(<DigestCoveragePage />);
    expect(container.querySelector(".digest-kpi-grid")).toBeTruthy();
  });

  it("shows a GraphQL error state", () => {
    setupUrqlHooks({ digest: null, error: new Error("network unreachable") });
    renderDigestPage(<DigestCoveragePage />);
    expect(screen.getByText("Digest could not be read")).toBeInTheDocument();
  });

  it("renders coverage percentage and extraction counts when available", () => {
    setupUrqlHooks({ digest: baseDigest });
    renderDigestPage(<DigestCoveragePage />);
    expect(screen.getByText("92.7%")).toBeInTheDocument();
    expect(screen.getByText("139 / 150 source files")).toBeInTheDocument();
    expect(screen.getByText("500")).toBeInTheDocument();
  });

  it("shows an honest unavailable state when coverageStats is null, never a fabricated percentage", () => {
    setupUrqlHooks({ digest: { ...baseDigest, coverageStats: null } });
    renderDigestPage(<DigestCoveragePage />);
    expect(screen.getByText(/Coverage statistics aren.t available/)).toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it("renders conflicts from gaps", () => {
    const digestWithGaps = {
      ...baseDigest,
      gaps: [{ type: "conflicting_commands", description: "Two sources disagree on the test command.", evidence: [] }],
    };
    setupUrqlHooks({ digest: digestWithGaps });
    renderDigestPage(<DigestCoveragePage />);
    expect(screen.getByText("conflicting commands")).toBeInTheDocument();
    expect(screen.getByText("Two sources disagree on the test command.")).toBeInTheDocument();
  });

  it("shows the no-conflicts state when gaps is empty", () => {
    setupUrqlHooks({ digest: { ...baseDigest, gaps: [] } });
    renderDigestPage(<DigestCoveragePage />);
    expect(screen.getByText("No conflicting or ambiguous sources were found during the last build.")).toBeInTheDocument();
  });

  it("shows the empty state when the project map has no indexed files", () => {
    setupUrqlHooks({ digest: { ...baseDigest, footprint: { ...baseDigest.footprint, fileCount: 0 } } });
    renderDigestPage(<DigestCoveragePage />);
    expect(screen.getByText(/Coverage and conflicts will populate once the repository has content/)).toBeInTheDocument();
  });

  it("handles a partial digest (no coverage, no gaps) without crashing", () => {
    setupUrqlHooks({ digest: partialDigest });
    renderDigestPage(<DigestCoveragePage />);
    expect(screen.getByText(/Coverage statistics aren.t available/)).toBeInTheDocument();
  });
});
