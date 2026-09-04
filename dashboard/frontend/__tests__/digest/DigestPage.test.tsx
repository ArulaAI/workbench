import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, fireEvent, waitFor } from "@testing-library/react";
import { baseDigest, partialDigest, staleDigest, baseStatus } from "./fixtures";
import { setupUrqlHooks as sharedSetupUrqlHooks, renderDigestPage, type UrqlHookOverrides } from "./testUtils";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/digest",
}));

vi.mock("urql", () => ({
  useQuery: vi.fn(),
  useMutation: vi.fn(),
  useSubscription: vi.fn(),
  gql: (strings: TemplateStringsArray) => strings.raw.join(""),
}));

import { useQuery, useMutation, useSubscription } from "urql";
import DigestOverviewPage from "@/app/digest/page";

const mockedUseQuery = vi.mocked(useQuery);
const mockedUseMutation = vi.mocked(useMutation);
const mockedUseSubscription = vi.mocked(useSubscription);

function setupUrqlHooks(overrides: UrqlHookOverrides = {}) {
  return sharedSetupUrqlHooks(mockedUseQuery, mockedUseMutation, mockedUseSubscription, overrides);
}

describe("DigestOverviewPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows a loading skeleton while fetching with no digest yet", () => {
    setupUrqlHooks({ digest: null, fetching: true, status: null });
    const { container } = renderDigestPage(<DigestOverviewPage />);
    expect(container.querySelector(".digest-kpi-grid")).toBeTruthy();
    expect(screen.queryByText("No repository digest yet")).not.toBeInTheDocument();
  });

  it("shows the missing-digest call to action when no digest has ever been built", () => {
    setupUrqlHooks({ digest: null, status: { ...baseStatus, state: "MISSING", hasReadableDigest: false, indexedGitHead: null, currentGitHead: null } });
    renderDigestPage(<DigestOverviewPage />);
    expect(screen.getByText("No repository digest yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Build digest" })).toBeInTheDocument();
  });

  it("makes 'Index repository and build digest' the primary action when the repository has never been indexed", () => {
    setupUrqlHooks({
      digest: null,
      status: {
        ...baseStatus, state: "MISSING", hasReadableDigest: false, hasProjectMap: false,
        indexedGitHead: null, currentGitHead: null,
      },
    });
    renderDigestPage(<DigestOverviewPage />);
    expect(screen.getByText("No repository digest yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Index repository and build digest" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Build digest" })).not.toBeInTheDocument();
  });

  it("shows the malformed-artifact state distinctly from missing", () => {
    setupUrqlHooks({
      digest: null,
      status: { ...baseStatus, state: "ERROR", hasReadableDigest: false, lastError: "repository-digest.json is not valid JSON" },
    });
    renderDigestPage(<DigestOverviewPage />);
    expect(screen.getByText("Repository digest is malformed")).toBeInTheDocument();
    expect(screen.getByText("repository-digest.json is not valid JSON")).toBeInTheDocument();
    expect(screen.queryByText("No repository digest yet")).not.toBeInTheDocument();
  });

  it("surfaces a GraphQL error state with a retry action", () => {
    setupUrqlHooks({ digest: null, error: new Error("network unreachable") });
    renderDigestPage(<DigestOverviewPage />);
    expect(screen.getByText("Digest could not be read")).toBeInTheDocument();
    expect(screen.getByText("network unreachable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Rebuild digest" })).toBeInTheDocument();
  });

  it("renders identity, footprint, language composition, and major domains for a complete digest", () => {
    setupUrqlHooks({ digest: baseDigest });
    renderDigestPage(<DigestOverviewPage />);
    expect(screen.getByText("speed")).toBeInTheDocument();
    expect(screen.getByText("Files")).toBeInTheDocument();
    expect(screen.getByText("Language composition")).toBeInTheDocument();
    expect(screen.getByText(/python/)).toBeInTheDocument();
    expect(screen.getByText("Major areas")).toBeInTheDocument();
    expect(screen.getAllByText("Core").length).toBeGreaterThan(0);
  });

  it("shows an em dash instead of a doubled middot when there is no git history", () => {
    // Max-effort code review finding: an unconditional `${shortHead}`
    // interpolation with no fallback for a null currentGitHead rendered
    // a visibly broken "CURRENT ·  · <date>" (empty segment, doubled
    // middot) instead of gracefully showing something in its place.
    const digestWithNoGitHead = {
      ...baseDigest,
      freshness: { ...baseDigest.freshness, currentGitHead: null },
    };
    setupUrqlHooks({ digest: digestWithNoGitHead });
    renderDigestPage(<DigestOverviewPage />);
    expect(screen.getByText(/CURRENT · — ·/)).toBeInTheDocument();
    expect(screen.queryByText(/CURRENT ·  ·/)).not.toBeInTheDocument();
  });

  it("does not render commands or conventions inline (moved to their own screens)", () => {
    setupUrqlHooks({ digest: baseDigest });
    renderDigestPage(<DigestOverviewPage />);
    expect(screen.queryByText("Entrypoints and commands")).not.toBeInTheDocument();
    expect(screen.queryByText("Conventions")).not.toBeInTheDocument();
  });

  it("shows the domains empty state for a partial digest instead of hiding the page", () => {
    setupUrqlHooks({ digest: partialDigest });
    renderDigestPage(<DigestOverviewPage />);
    expect(screen.getByText("No areas available — semantic graph not yet built.")).toBeInTheDocument();
  });

  it("shows a stale banner with the indexed-versus-current commit when the digest is out of date", () => {
    setupUrqlHooks({ digest: staleDigest });
    renderDigestPage(<DigestOverviewPage />);
    expect(screen.getByText(/Changed content may make domains and hotspots inaccurate/)).toBeInTheDocument();
  });

  it("starts a refresh when the header refresh button is clicked", async () => {
    const { executeRefresh } = setupUrqlHooks({ digest: baseDigest });
    renderDigestPage(<DigestOverviewPage />);
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => {
      expect(executeRefresh).toHaveBeenCalledWith({ rebuildDiscovery: false, narrative: false });
    });
  });

  it("shows a dismissible error banner when a refresh request fails", async () => {
    const executeRefresh = vi.fn().mockResolvedValue({ error: { message: "Digest build failed: no project map found" } });
    setupUrqlHooks({ digest: baseDigest, executeRefresh });
    renderDigestPage(<DigestOverviewPage />);

    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => {
      expect(screen.getByText("Digest build failed: no project map found")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByText("Digest build failed: no project map found")).not.toBeInTheDocument();
  });

  it("polls repositoryDigestStatus while generating, so a dead/unavailable subscription isn't the only way to end a refresh", () => {
    vi.useFakeTimers();
    try {
      const reexecuteStatusQuery = vi.fn();
      mockedUseQuery.mockImplementation((opts: any) => {
        const query = String(opts.query);
        if (query.includes("RepositoryDigestStatus")) {
          return [
            { data: { repositoryDigestStatus: { ...baseStatus, state: "GENERATING", startedAt: "2026-03-15T10:00:00Z" } }, fetching: false, error: null, stale: false, extensions: undefined },
            reexecuteStatusQuery,
          ] as unknown as ReturnType<typeof useQuery>;
        }
        return [
          { data: { repositoryDigest: baseDigest }, fetching: false, error: null, stale: false, extensions: undefined },
          vi.fn(),
        ] as unknown as ReturnType<typeof useQuery>;
      });
      mockedUseMutation.mockReturnValue([
        { fetching: false, stale: false, error: undefined, extensions: undefined, data: undefined },
        vi.fn(),
      ] as unknown as ReturnType<typeof useMutation>);
      mockedUseSubscription.mockReturnValue([
        { data: undefined, error: null, fetching: false, stale: false, extensions: undefined },
        vi.fn(),
      ] as unknown as ReturnType<typeof useSubscription>);

      renderDigestPage(<DigestOverviewPage />);
      // A GENERATING status observed on load (no local refresh click at
      // all — this simulates another owner's build already in flight,
      // or a subscription that never delivered a first event) must
      // still trigger polling.
      reexecuteStatusQuery.mockClear();
      vi.advanceTimersByTime(2500);
      expect(reexecuteStatusQuery).toHaveBeenCalledWith({ requestPolicy: "network-only" });
    } finally {
      vi.useRealTimers();
    }
  });
});
