import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import { baseDigest, partialDigest, staleDigest } from "./fixtures";
import { setupUrqlHooks as sharedSetupUrqlHooks, renderDigestPage, type UrqlHookOverrides } from "./testUtils";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/digest/quality",
}));

vi.mock("urql", () => ({
  useQuery: vi.fn(),
  useMutation: vi.fn(),
  useSubscription: vi.fn(),
  gql: (strings: TemplateStringsArray) => strings.raw.join(""),
}));

import { useQuery, useMutation, useSubscription } from "urql";
import DigestQualityPage from "@/app/digest/quality/page";

const mockedUseQuery = vi.mocked(useQuery);
const mockedUseMutation = vi.mocked(useMutation);
const mockedUseSubscription = vi.mocked(useSubscription);

function setupUrqlHooks(overrides: UrqlHookOverrides = {}) {
  return sharedSetupUrqlHooks(mockedUseQuery, mockedUseMutation, mockedUseSubscription, overrides);
}

describe("DigestQualityPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows a loading skeleton while fetching", () => {
    setupUrqlHooks({ digest: null, fetching: true, status: null });
    const { container } = renderDigestPage(<DigestQualityPage />);
    expect(container.querySelector(".digest-kpi-grid")).toBeTruthy();
  });

  it("shows a GraphQL error state", () => {
    setupUrqlHooks({ digest: null, error: new Error("network unreachable") });
    renderDigestPage(<DigestQualityPage />);
    expect(screen.getByText("Digest could not be read")).toBeInTheDocument();
  });

  it("renders readiness and quality warnings for a complete digest", () => {
    setupUrqlHooks({ digest: baseDigest });
    renderDigestPage(<DigestQualityPage />);
    expect(screen.getByText("Discovery readiness")).toBeInTheDocument();
    expect(screen.getByText("semantic graph")).toBeInTheDocument();
    expect(screen.getByText("Quality warnings")).toBeInTheDocument();
    expect(screen.getByText("2 domains have no distinguishing label and were marked unresolved.")).toBeInTheDocument();
  });

  it("shows the no-warnings message when there are none", () => {
    setupUrqlHooks({ digest: partialDigest });
    renderDigestPage(<DigestQualityPage />);
    expect(screen.getByText("No quality warnings were raised during the last build.")).toBeInTheDocument();
  });

  it("shows freshness state and stale reasons", () => {
    setupUrqlHooks({ digest: staleDigest });
    renderDigestPage(<DigestQualityPage />);
    expect(screen.getByText("STALE")).toBeInTheDocument();
    expect(screen.getByText(/Stale because: git_head/)).toBeInTheDocument();
  });

  it("shows the empty state when the project map has no indexed files", () => {
    setupUrqlHooks({ digest: { ...baseDigest, footprint: { ...baseDigest.footprint, fileCount: 0 } } });
    renderDigestPage(<DigestQualityPage />);
    expect(screen.getByText(/Readiness and warnings will populate once the repository has content/)).toBeInTheDocument();
  });
});
