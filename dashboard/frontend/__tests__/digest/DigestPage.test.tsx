import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import type {
  RepositoryDigestData,
  RepositoryDigestBuildStatus,
} from "@/lib/graphql/queries/repository-digest";

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
import DigestPage from "@/app/digest/page";

const mockedUseQuery = vi.mocked(useQuery);
const mockedUseMutation = vi.mocked(useMutation);
const mockedUseSubscription = vi.mocked(useSubscription);

// --- Fixtures ---

const baseDigest: RepositoryDigestData = {
  schemaVersion: 1,
  status: "COMPLETE",
  effectiveState: "CURRENT",
  generatedAt: "2026-03-15T10:00:00Z",
  freshness: {
    state: "CURRENT",
    indexedGitHead: "abc1234567",
    currentGitHead: "abc1234567",
    generatedAt: "2026-03-15T10:00:00Z",
    staleReasons: [],
  },
  identity: { name: "speed", summary: "An orchestration framework.", confidence: "DERIVED", evidence: [] },
  footprint: {
    fileCount: 120,
    lineCount: 34000,
    symbolCount: 500,
    domainCount: 3,
    languages: [{ name: "python", files: 80, lines: 20000, percent: 60 }],
  },
  domains: [
    {
      id: "cluster-core",
      label: "Core",
      summary: "Core orchestration logic.",
      confidence: "DERIVED",
      fileCount: 40,
      symbolCount: 200,
      representativeFiles: ["lib/context/repository_digest.py"],
      representativeSymbols: [],
      dependsOn: [],
      usedBy: [],
      evidence: [{ source: "semantic_graph", path: "lib/context/repository_digest.py", line: null, symbol: null, artifactKey: null, description: "evidence" }],
    },
  ],
  commands: [
    { purpose: "test", command: "npm run test", workingDirectory: ".", confidence: "CONFIRMED", evidence: [] },
  ],
  hotspots: [],
  conventions: [
    { text: "Use snake_case for Python modules.", scope: ["lib"], confidence: "DERIVED", evidence: [] },
  ],
  risks: [],
  gaps: [],
  readiness: [
    { capability: "semantic_graph", status: "AVAILABLE", reason: null, remediation: null },
  ],
  warnings: [],
};

const partialDigest: RepositoryDigestData = {
  ...baseDigest,
  status: "PARTIAL",
  footprint: { ...baseDigest.footprint, symbolCount: null, domainCount: null },
  domains: [],
  commands: [],
  conventions: [],
  readiness: [
    { capability: "semantic_graph", status: "UNAVAILABLE", reason: "semantic-graph.json does not exist", remediation: "Run the Layer 1 context build" },
  ],
};

const staleDigest: RepositoryDigestData = {
  ...baseDigest,
  effectiveState: "STALE",
  freshness: { ...baseDigest.freshness, state: "STALE", currentGitHead: "def7654321", staleReasons: ["git_head"] },
};

const baseStatus: RepositoryDigestBuildStatus = {
  state: "CURRENT",
  startedAt: null,
  completedAt: "2026-03-15T10:00:00Z",
  lastError: null,
  hasReadableDigest: true,
  indexedGitHead: "abc1234567",
  currentGitHead: "abc1234567",
  staleReasons: [],
};

function setupUrqlHooks(overrides: {
  digest?: RepositoryDigestData | null;
  fetching?: boolean;
  error?: Error | null;
  status?: RepositoryDigestBuildStatus | null;
  executeRefresh?: ReturnType<typeof vi.fn>;
} = {}) {
  const {
    digest = baseDigest,
    fetching = false,
    error = null,
    status = baseStatus,
    executeRefresh = vi.fn().mockResolvedValue({ data: { refreshRepositoryDigest: { accepted: true } } }),
  } = overrides;

  mockedUseQuery.mockImplementation((opts: any) => {
    const query = String(opts.query);
    if (query.includes("RepositoryDigestStatus")) {
      return [
        { data: status ? { repositoryDigestStatus: status } : undefined, fetching: false, error: null, stale: false, extensions: undefined },
        vi.fn(),
      ] as unknown as ReturnType<typeof useQuery>;
    }
    return [
      { data: { repositoryDigest: digest }, fetching, error, stale: false, extensions: undefined },
      vi.fn(),
    ] as unknown as ReturnType<typeof useQuery>;
  });

  mockedUseMutation.mockReturnValue([
    { fetching: false, stale: false, error: undefined, extensions: undefined, data: undefined },
    executeRefresh,
  ] as unknown as ReturnType<typeof useMutation>);

  mockedUseSubscription.mockReturnValue([
    { data: undefined, error: null, fetching: false, stale: false, extensions: undefined },
    vi.fn(),
  ] as unknown as ReturnType<typeof useSubscription>);

  return { executeRefresh };
}

describe("DigestPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows a loading skeleton while fetching with no digest yet", () => {
    setupUrqlHooks({ digest: null, fetching: true, status: null });
    const { container } = render(<DigestPage />);
    expect(container.querySelector(".digest-kpi-grid")).toBeTruthy();
    expect(screen.queryByText("No repository digest yet")).not.toBeInTheDocument();
  });

  it("shows the missing-digest call to action when no digest has ever been built", () => {
    setupUrqlHooks({ digest: null, status: { ...baseStatus, state: "MISSING", hasReadableDigest: false, indexedGitHead: null, currentGitHead: null } });
    render(<DigestPage />);
    expect(screen.getByText("No repository digest yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Build digest" })).toBeInTheDocument();
  });

  it("shows the malformed-artifact state distinctly from missing", () => {
    setupUrqlHooks({
      digest: null,
      status: { ...baseStatus, state: "ERROR", hasReadableDigest: false, lastError: "repository-digest.json is not valid JSON" },
    });
    render(<DigestPage />);
    expect(screen.getByText("Repository digest is malformed")).toBeInTheDocument();
    expect(screen.getByText("repository-digest.json is not valid JSON")).toBeInTheDocument();
    expect(screen.queryByText("No repository digest yet")).not.toBeInTheDocument();
  });

  it("renders identity, footprint, domains, commands, and conventions for a complete digest", () => {
    setupUrqlHooks({ digest: baseDigest });
    render(<DigestPage />);
    expect(screen.getByText("speed")).toBeInTheDocument();
    expect(screen.getByText("Major domains")).toBeInTheDocument();
    expect(screen.getAllByText("Core").length).toBeGreaterThan(0);
    expect(screen.getByText("Entrypoints and commands")).toBeInTheDocument();
    expect(screen.getByText("Conventions")).toBeInTheDocument();
  });

  it("shows each section's own empty state for a partial digest instead of hiding the page", () => {
    setupUrqlHooks({ digest: partialDigest });
    render(<DigestPage />);
    expect(screen.getByText("No domains available — semantic graph not yet built.")).toBeInTheDocument();
    expect(screen.getByText("No commands discovered in CLAUDE.md, AGENTS.md, or project manifests.")).toBeInTheDocument();
    expect(screen.getByText("No approved conventions available.")).toBeInTheDocument();
  });

  it("shows a stale banner with the indexed-versus-current commit when the digest is out of date", () => {
    setupUrqlHooks({ digest: staleDigest });
    render(<DigestPage />);
    expect(screen.getByText(/Changed content may make domains and hotspots inaccurate/)).toBeInTheDocument();
  });

  it("starts a refresh when the header refresh button is clicked", async () => {
    const { executeRefresh } = setupUrqlHooks({ digest: baseDigest });
    render(<DigestPage />);
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => {
      expect(executeRefresh).toHaveBeenCalledWith({ rebuildDiscovery: false, narrative: false });
    });
  });

  it("shows a dismissible error banner when a refresh request fails", async () => {
    const executeRefresh = vi.fn().mockResolvedValue({ error: { message: "Digest build failed: no project map found" } });
    setupUrqlHooks({ digest: baseDigest, executeRefresh });
    render(<DigestPage />);

    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => {
      expect(screen.getByText("Digest build failed: no project map found")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByText("Digest build failed: no project map found")).not.toBeInTheDocument();
  });
});
