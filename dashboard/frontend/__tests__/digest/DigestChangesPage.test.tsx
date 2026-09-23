import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, within } from "@testing-library/react";
import { baseDigest, partialDigest } from "./fixtures";
import { setupUrqlHooks as sharedSetupUrqlHooks, renderDigestPage, type UrqlHookOverrides } from "./testUtils";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/digest/changes",
}));

vi.mock("urql", () => ({
  useQuery: vi.fn(),
  useMutation: vi.fn(),
  useSubscription: vi.fn(),
  gql: (strings: TemplateStringsArray) => strings.raw.join(""),
}));

import { useQuery, useMutation, useSubscription } from "urql";
import DigestChangesPage from "@/app/digest/changes/page";

const mockedUseQuery = vi.mocked(useQuery);
const mockedUseMutation = vi.mocked(useMutation);
const mockedUseSubscription = vi.mocked(useSubscription);

function setupUrqlHooks(overrides: UrqlHookOverrides = {}) {
  return sharedSetupUrqlHooks(mockedUseQuery, mockedUseMutation, mockedUseSubscription, overrides);
}

describe("DigestChangesPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows a loading skeleton while fetching", () => {
    setupUrqlHooks({ digest: null, fetching: true, status: null });
    const { container } = renderDigestPage(<DigestChangesPage />);
    expect(container.querySelector(".digest-kpi-grid")).toBeTruthy();
  });

  it("shows a GraphQL error state", () => {
    setupUrqlHooks({ digest: null, error: new Error("network unreachable") });
    renderDigestPage(<DigestChangesPage />);
    expect(screen.getByText("Digest could not be read")).toBeInTheDocument();
  });

  it("renders the comparison header with both snapshot timestamps", () => {
    setupUrqlHooks({ digest: baseDigest });
    renderDigestPage(<DigestChangesPage />);
    expect(screen.getByText("2026-03-14T10:00:00Z")).toBeInTheDocument();
    expect(screen.getByText("2026-03-15T10:00:00Z")).toBeInTheDocument();
  });

  it("renders the summary lines", () => {
    setupUrqlHooks({ digest: baseDigest });
    renderDigestPage(<DigestChangesPage />);
    expect(screen.getByText("+1 domain")).toBeInTheDocument();
    expect(screen.getByText("-1 api route")).toBeInTheDocument();
    expect(screen.getByText("Runtime (python) changed from 3.11 to 3.12")).toBeInTheDocument();
  });

  it("renders added, removed, and changed entries in their own sections with evidence-worthy detail", () => {
    setupUrqlHooks({ digest: baseDigest });
    renderDigestPage(<DigestChangesPage />);

    const domainsSection = screen.getByText("Domains").closest(".surface") as HTMLElement;
    expect(within(domainsSection).getByText("added")).toBeInTheDocument();
    expect(within(domainsSection).getByText("Dashboard UI")).toBeInTheDocument();

    const routesSection = screen.getByText("API routes").closest(".surface") as HTMLElement;
    expect(within(routesSection).getByText("removed")).toBeInTheDocument();
    expect(within(routesSection).getByText("GET /old-endpoint")).toBeInTheDocument();

    const runtimesSection = screen.getByText("Runtimes").closest(".surface") as HTMLElement;
    expect(within(runtimesSection).getByText("changed")).toBeInTheDocument();
    expect(within(runtimesSection).getByText(/version: 3.11 → 3.12/)).toBeInTheDocument();
  });

  it("shows unavailable sections as 'not comparable', never as fabricated removals", () => {
    setupUrqlHooks({ digest: baseDigest });
    renderDigestPage(<DigestChangesPage />);
    expect(screen.getByText("Not comparable")).toBeInTheDocument();
    const section = screen.getByText("Not comparable").closest(".surface") as HTMLElement;
    expect(within(section).getByText("CI/CD workflows")).toBeInTheDocument();
    expect(within(section).getByText(/schema predates this section/)).toBeInTheDocument();
  });

  it("shows the first-run state, never fake changes, when there is no previous snapshot", () => {
    setupUrqlHooks({
      digest: {
        ...baseDigest,
        changesHistory: {
          status: "FIRST_RUN", previousSnapshot: null,
          currentSnapshot: { generatedAt: "2026-03-15T10:00:00Z", gitHead: "abc1234567", identityName: "speed", schemaVersion: 9 },
          summary: [], warnings: [], sections: [],
        },
      },
    });
    renderDigestPage(<DigestChangesPage />);
    expect(screen.getByText("No previous digest is available yet")).toBeInTheDocument();
    expect(screen.queryByText("Summary")).not.toBeInTheDocument();
  });

  it("shows a no-changes message when compared but nothing changed", () => {
    setupUrqlHooks({
      digest: {
        ...baseDigest,
        changesHistory: {
          status: "COMPARED",
          previousSnapshot: { generatedAt: "2026-03-14T10:00:00Z", gitHead: "abc1111111", identityName: "speed", schemaVersion: 9 },
          currentSnapshot: { generatedAt: "2026-03-15T10:00:00Z", gitHead: "abc1234567", identityName: "speed", schemaVersion: 9 },
          summary: [], warnings: [], sections: [],
        },
      },
    });
    renderDigestPage(<DigestChangesPage />);
    expect(screen.getByText("No meaningful changes were detected since the last digest.")).toBeInTheDocument();
  });

  it("renders warnings, e.g. missing git revision, without crashing", () => {
    setupUrqlHooks({
      digest: {
        ...baseDigest,
        changesHistory: {
          status: "COMPARED",
          previousSnapshot: { generatedAt: "2026-03-14T10:00:00Z", gitHead: null, identityName: "speed", schemaVersion: 9 },
          currentSnapshot: { generatedAt: "2026-03-15T10:00:00Z", gitHead: null, identityName: "speed", schemaVersion: 9 },
          summary: [], warnings: ["git revision unavailable for one or both snapshots — comparison is based on digest content only, not a commit range"],
          sections: [],
        },
      },
    });
    renderDigestPage(<DigestChangesPage />);
    expect(screen.getByText(/comparison is based on digest content only/)).toBeInTheDocument();
    expect(screen.getAllByText("git revision unavailable").length).toBeGreaterThan(0);
  });

  it("shows an honest unavailable state when changesHistory is null", () => {
    setupUrqlHooks({ digest: { ...baseDigest, changesHistory: null } });
    renderDigestPage(<DigestChangesPage />);
    expect(screen.getByText(/Changes history isn.t available/)).toBeInTheDocument();
  });

  it("handles a partial digest without crashing", () => {
    setupUrqlHooks({ digest: partialDigest });
    renderDigestPage(<DigestChangesPage />);
    expect(screen.getByText(/Changes history isn.t available/)).toBeInTheDocument();
  });

  it("shows the page-level empty state when the project map has no indexed files", () => {
    setupUrqlHooks({ digest: { ...baseDigest, footprint: { ...baseDigest.footprint, fileCount: 0 } } });
    renderDigestPage(<DigestChangesPage />);
    expect(screen.getByText(/Changes history will populate once the repository has content/)).toBeInTheDocument();
  });
});
