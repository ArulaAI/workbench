import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import { baseDigest, partialDigest } from "./fixtures";
import { setupUrqlHooks as sharedSetupUrqlHooks, renderDigestPage, type UrqlHookOverrides } from "./testUtils";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/digest/knowledge",
}));

vi.mock("urql", () => ({
  useQuery: vi.fn(),
  useMutation: vi.fn(),
  useSubscription: vi.fn(),
  gql: (strings: TemplateStringsArray) => strings.raw.join(""),
}));

import { useQuery, useMutation, useSubscription } from "urql";
import DigestKnowledgePage from "@/app/digest/knowledge/page";

const mockedUseQuery = vi.mocked(useQuery);
const mockedUseMutation = vi.mocked(useMutation);
const mockedUseSubscription = vi.mocked(useSubscription);

function setupUrqlHooks(overrides: UrqlHookOverrides = {}) {
  return sharedSetupUrqlHooks(mockedUseQuery, mockedUseMutation, mockedUseSubscription, overrides);
}

describe("DigestKnowledgePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows a loading skeleton while fetching", () => {
    setupUrqlHooks({ digest: null, fetching: true, status: null });
    const { container } = renderDigestPage(<DigestKnowledgePage />);
    expect(container.querySelector(".digest-kpi-grid")).toBeTruthy();
  });

  it("shows a GraphQL error state", () => {
    setupUrqlHooks({ digest: null, error: new Error("network unreachable") });
    renderDigestPage(<DigestKnowledgePage />);
    expect(screen.getByText("Digest could not be read")).toBeInTheDocument();
  });

  it("renders existing conventions via the reused ConventionsPanel", () => {
    setupUrqlHooks({ digest: baseDigest });
    renderDigestPage(<DigestKnowledgePage />);
    expect(screen.getByText("Conventions")).toBeInTheDocument();
    expect(screen.getByText("Use snake_case for Python modules.")).toBeInTheDocument();
  });

  it("renders approved project knowledge", () => {
    setupUrqlHooks({ digest: baseDigest });
    renderDigestPage(<DigestKnowledgePage />);
    expect(screen.getByText("Approved project knowledge")).toBeInTheDocument();
    expect(screen.getByText("Persistence mode is profile-selected.")).toBeInTheDocument();
  });

  it("renders pending drafts, visibly separate from approved knowledge", () => {
    setupUrqlHooks({ digest: baseDigest });
    renderDigestPage(<DigestKnowledgePage />);
    expect(screen.getByText("Pending human review")).toBeInTheDocument();
    expect(screen.getByText("Document client test enforcement.")).toBeInTheDocument();
  });

  it("renders recurring signals from repeated_failure risks only", () => {
    const digestWithRisks = {
      ...baseDigest,
      risks: [
        { type: "REPEATED_FAILURE", description: "3 'gate_failure' observations share scope 'lib/x.py'.", severity: "medium", domainId: "", evidence: [] },
        { type: "HIGH_BLAST_RADIUS", description: "Should not appear here.", severity: "high", domainId: "", evidence: [] },
      ],
    };
    setupUrqlHooks({ digest: digestWithRisks });
    renderDigestPage(<DigestKnowledgePage />);
    expect(screen.getByText("3 'gate_failure' observations share scope 'lib/x.py'.")).toBeInTheDocument();
    expect(screen.queryByText("Should not appear here.")).not.toBeInTheDocument();
  });

  it("shows honest empty states when no knowledge/drafts/signals exist", () => {
    setupUrqlHooks({ digest: partialDigest });
    renderDigestPage(<DigestKnowledgePage />);
    expect(screen.getByText("No approved project knowledge is available yet.")).toBeInTheDocument();
    expect(screen.getByText("No drafts are pending review.")).toBeInTheDocument();
    expect(screen.getByText("No recurring failure patterns have been observed.")).toBeInTheDocument();
  });

  it("shows the page-level empty state when the project map has no indexed files", () => {
    setupUrqlHooks({ digest: { ...baseDigest, footprint: { ...baseDigest.footprint, fileCount: 0 } } });
    renderDigestPage(<DigestKnowledgePage />);
    expect(screen.getByText(/Conventions and knowledge will populate once the repository has content/)).toBeInTheDocument();
  });
});
