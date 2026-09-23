import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, within } from "@testing-library/react";
import { baseDigest, partialDigest } from "./fixtures";
import { setupUrqlHooks as sharedSetupUrqlHooks, renderDigestPage, type UrqlHookOverrides } from "./testUtils";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/digest/runtime",
}));

vi.mock("urql", () => ({
  useQuery: vi.fn(),
  useMutation: vi.fn(),
  useSubscription: vi.fn(),
  gql: (strings: TemplateStringsArray) => strings.raw.join(""),
}));

import { useQuery, useMutation, useSubscription } from "urql";
import DigestRuntimePage from "@/app/digest/runtime/page";

const mockedUseQuery = vi.mocked(useQuery);
const mockedUseMutation = vi.mocked(useMutation);
const mockedUseSubscription = vi.mocked(useSubscription);

function setupUrqlHooks(overrides: UrqlHookOverrides = {}) {
  return sharedSetupUrqlHooks(mockedUseQuery, mockedUseMutation, mockedUseSubscription, overrides);
}

describe("DigestRuntimePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows a loading skeleton while fetching", () => {
    setupUrqlHooks({ digest: null, fetching: true, status: null });
    const { container } = renderDigestPage(<DigestRuntimePage />);
    expect(container.querySelector(".digest-kpi-grid")).toBeTruthy();
  });

  it("shows a GraphQL error state", () => {
    setupUrqlHooks({ digest: null, error: new Error("network unreachable") });
    renderDigestPage(<DigestRuntimePage />);
    expect(screen.getByText("Digest could not be read")).toBeInTheDocument();
  });

  it("renders discovered runtimes and frameworks", () => {
    setupUrqlHooks({ digest: baseDigest });
    renderDigestPage(<DigestRuntimePage />);
    expect(screen.getByText("python")).toBeInTheDocument();
    expect(screen.getByText("3.12-slim")).toBeInTheDocument();
    expect(screen.getByText("fastapi")).toBeInTheDocument();
  });

  it("renders config sources as badges", () => {
    setupUrqlHooks({ digest: baseDigest });
    renderDigestPage(<DigestRuntimePage />);
    const section = screen.getByText("Configuration sources").closest(".surface") as HTMLElement;
    expect(within(section).getByText("Dockerfile")).toBeInTheDocument();
  });

  it("renders environment variable names only, and flags sensitive-looking names", () => {
    // "declared" (not "configured"): the digest only proves the variable
    // name was referenced somewhere — never that a value is actually set.
    setupUrqlHooks({ digest: baseDigest });
    renderDigestPage(<DigestRuntimePage />);
    const row = screen.getByText("OPENAI_API_KEY").closest("tr") as HTMLElement;
    expect(within(row).getByText("secret/declared")).toBeInTheDocument();

    const otherRow = screen.getByText("DATABASE_URL").closest("tr") as HTMLElement;
    expect(within(otherRow).getByText("declared")).toBeInTheDocument();

    // The page must never render a raw value — only the fixture's own
    // name/source/flag fields, none of which is ever a secret value.
    expect(screen.queryByText(/sk-|postgres:\/\//)).not.toBeInTheDocument();
  });

  it("shows an honest empty state when runtimeConfig is null", () => {
    setupUrqlHooks({ digest: { ...baseDigest, runtimeConfig: null } });
    renderDigestPage(<DigestRuntimePage />);
    expect(screen.getByText(/Runtime and configuration information isn.t available/)).toBeInTheDocument();
  });

  it("shows empty-state messages for each empty section", () => {
    setupUrqlHooks({
      digest: {
        ...baseDigest,
        runtimeConfig: { runtimes: [], frameworks: [], configSources: [], environmentVariables: [] },
      },
    });
    renderDigestPage(<DigestRuntimePage />);
    expect(screen.getByText("No runtime versions were explicitly declared.")).toBeInTheDocument();
    expect(screen.getByText("No known frameworks were found among declared dependencies.")).toBeInTheDocument();
    expect(screen.getByText("No known configuration files were found at the repository root.")).toBeInTheDocument();
    expect(screen.getByText("No environment variable names were discovered.")).toBeInTheDocument();
  });

  it("handles a partial digest without crashing", () => {
    setupUrqlHooks({ digest: partialDigest });
    renderDigestPage(<DigestRuntimePage />);
    expect(screen.getByText(/Runtime and configuration information isn.t available/)).toBeInTheDocument();
  });

  it("shows the page-level empty state when the project map has no indexed files", () => {
    setupUrqlHooks({ digest: { ...baseDigest, footprint: { ...baseDigest.footprint, fileCount: 0 } } });
    renderDigestPage(<DigestRuntimePage />);
    expect(screen.getByText(/Runtime and configuration information will populate once the repository has content/)).toBeInTheDocument();
  });
});
