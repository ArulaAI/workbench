import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import { baseDigest, partialDigest } from "./fixtures";
import { setupUrqlHooks as sharedSetupUrqlHooks, renderDigestPage, type UrqlHookOverrides } from "./testUtils";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/digest/cicd",
}));

vi.mock("urql", () => ({
  useQuery: vi.fn(),
  useMutation: vi.fn(),
  useSubscription: vi.fn(),
  gql: (strings: TemplateStringsArray) => strings.raw.join(""),
}));

import { useQuery, useMutation, useSubscription } from "urql";
import DigestCicdPage from "@/app/digest/cicd/page";

const mockedUseQuery = vi.mocked(useQuery);
const mockedUseMutation = vi.mocked(useMutation);
const mockedUseSubscription = vi.mocked(useSubscription);

function setupUrqlHooks(overrides: UrqlHookOverrides = {}) {
  return sharedSetupUrqlHooks(mockedUseQuery, mockedUseMutation, mockedUseSubscription, overrides);
}

describe("DigestCicdPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows a loading skeleton while fetching", () => {
    setupUrqlHooks({ digest: null, fetching: true, status: null });
    const { container } = renderDigestPage(<DigestCicdPage />);
    expect(container.querySelector(".digest-kpi-grid")).toBeTruthy();
  });

  it("shows a GraphQL error state", () => {
    setupUrqlHooks({ digest: null, error: new Error("network unreachable") });
    renderDigestPage(<DigestCicdPage />);
    expect(screen.getByText("Digest could not be read")).toBeInTheDocument();
  });

  it("renders a discovered workflow with jobs, triggers, needs, and commands", () => {
    setupUrqlHooks({ digest: baseDigest });
    renderDigestPage(<DigestCicdPage />);
    expect(screen.getByText("CI")).toBeInTheDocument();
    expect(screen.getByText("github_actions")).toBeInTheDocument();
    expect(screen.getByText(/Triggers: push/)).toBeInTheDocument();
    expect(screen.getByText("test")).toBeInTheDocument();
    expect(screen.getByText("pytest")).toBeInTheDocument();
  });

  it("shows an honest empty state when cicd is null", () => {
    setupUrqlHooks({ digest: { ...baseDigest, cicd: null } });
    renderDigestPage(<DigestCicdPage />);
    expect(screen.getByText(/CI\/CD information isn.t available/)).toBeInTheDocument();
  });

  it("shows the no-workflows message when the array is empty", () => {
    setupUrqlHooks({ digest: { ...baseDigest, cicd: { workflows: [], otherProvidersDetected: [] } } });
    renderDigestPage(<DigestCicdPage />);
    expect(screen.getByText("No CI/CD workflows were discovered.")).toBeInTheDocument();
  });

  it("renders detected-but-not-parsed other CI providers separately", () => {
    setupUrqlHooks({
      digest: {
        ...baseDigest,
        cicd: { workflows: [], otherProvidersDetected: [{ provider: "gitlab_ci", configFile: ".gitlab-ci.yml", evidence: [] }] },
      },
    });
    renderDigestPage(<DigestCicdPage />);
    expect(screen.getByText(/gitlab_ci/)).toBeInTheDocument();
    expect(screen.getByText(".gitlab-ci.yml")).toBeInTheDocument();
  });

  it("handles a partial digest without crashing", () => {
    setupUrqlHooks({ digest: partialDigest });
    renderDigestPage(<DigestCicdPage />);
    expect(screen.getByText(/CI\/CD information isn.t available/)).toBeInTheDocument();
  });

  it("shows the page-level empty state when the project map has no indexed files", () => {
    setupUrqlHooks({ digest: { ...baseDigest, footprint: { ...baseDigest.footprint, fileCount: 0 } } });
    renderDigestPage(<DigestCicdPage />);
    expect(screen.getByText(/CI\/CD information will populate once the repository has content/)).toBeInTheDocument();
  });
});
