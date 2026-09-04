import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import { baseDigest, partialDigest } from "./fixtures";
import { setupUrqlHooks as sharedSetupUrqlHooks, renderDigestPage, type UrqlHookOverrides } from "./testUtils";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/digest/api-data",
}));

vi.mock("urql", () => ({
  useQuery: vi.fn(),
  useMutation: vi.fn(),
  useSubscription: vi.fn(),
  gql: (strings: TemplateStringsArray) => strings.raw.join(""),
}));

import { useQuery, useMutation, useSubscription } from "urql";
import DigestApiDataPage from "@/app/digest/api-data/page";

const mockedUseQuery = vi.mocked(useQuery);
const mockedUseMutation = vi.mocked(useMutation);
const mockedUseSubscription = vi.mocked(useSubscription);

function setupUrqlHooks(overrides: UrqlHookOverrides = {}) {
  return sharedSetupUrqlHooks(mockedUseQuery, mockedUseMutation, mockedUseSubscription, overrides);
}

describe("DigestApiDataPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows a loading skeleton while fetching", () => {
    setupUrqlHooks({ digest: null, fetching: true, status: null });
    const { container } = renderDigestPage(<DigestApiDataPage />);
    expect(container.querySelector(".digest-kpi-grid")).toBeTruthy();
  });

  it("shows a GraphQL error state", () => {
    setupUrqlHooks({ digest: null, error: new Error("network unreachable") });
    renderDigestPage(<DigestApiDataPage />);
    expect(screen.getByText("Digest could not be read")).toBeInTheDocument();
  });

  it("renders discovered routes with evidence-backed detail", () => {
    setupUrqlHooks({ digest: baseDigest });
    renderDigestPage(<DigestApiDataPage />);
    expect(screen.getByText("GET")).toBeInTheDocument();
    expect(screen.getByText("/users/{id}")).toBeInTheDocument();
    expect(screen.getByText("get_user")).toBeInTheDocument();
  });

  it("renders discovered entities with the inferred badge on reconstructed columns", () => {
    setupUrqlHooks({ digest: baseDigest });
    renderDigestPage(<DigestApiDataPage />);
    expect(screen.getByText("Owner")).toBeInTheDocument();
    expect(screen.getByText("inferred")).toBeInTheDocument();
    expect(screen.getByText(/id \(PK\)/)).toBeInTheDocument();
  });

  it("shows an honest empty state when apiData is null, never fabricated routes", () => {
    setupUrqlHooks({ digest: { ...baseDigest, apiData: null } });
    renderDigestPage(<DigestApiDataPage />);
    expect(screen.getByText(/API & data information isn.t available/)).toBeInTheDocument();
  });

  it("shows the no-routes and no-entities messages when arrays are empty", () => {
    setupUrqlHooks({
      digest: { ...baseDigest, apiData: { routes: [], entities: [], persistenceSummary: null } },
    });
    renderDigestPage(<DigestApiDataPage />);
    expect(screen.getByText("No API routes were discovered from supported frameworks.")).toBeInTheDocument();
    expect(screen.getByText("No ORM entities were discovered.")).toBeInTheDocument();
  });

  it("handles a partial digest without crashing", () => {
    setupUrqlHooks({ digest: partialDigest });
    renderDigestPage(<DigestApiDataPage />);
    expect(screen.getByText(/API & data information isn.t available/)).toBeInTheDocument();
  });

  it("shows the page-level empty state when the project map has no indexed files", () => {
    setupUrqlHooks({ digest: { ...baseDigest, footprint: { ...baseDigest.footprint, fileCount: 0 } } });
    renderDigestPage(<DigestApiDataPage />);
    expect(screen.getByText(/API and data information will populate once the repository has content/)).toBeInTheDocument();
  });
});
