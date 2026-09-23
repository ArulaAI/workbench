import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, within } from "@testing-library/react";
import { baseDigest, partialDigest } from "./fixtures";
import { setupUrqlHooks as sharedSetupUrqlHooks, renderDigestPage, type UrqlHookOverrides } from "./testUtils";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/digest/start",
}));

vi.mock("urql", () => ({
  useQuery: vi.fn(),
  useMutation: vi.fn(),
  useSubscription: vi.fn(),
  gql: (strings: TemplateStringsArray) => strings.raw.join(""),
}));

import { useQuery, useMutation, useSubscription } from "urql";
import DigestStartPage from "@/app/digest/start/page";

const mockedUseQuery = vi.mocked(useQuery);
const mockedUseMutation = vi.mocked(useMutation);
const mockedUseSubscription = vi.mocked(useSubscription);

function setupUrqlHooks(overrides: UrqlHookOverrides = {}) {
  return sharedSetupUrqlHooks(mockedUseQuery, mockedUseMutation, mockedUseSubscription, overrides);
}

describe("DigestStartPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows a loading skeleton while fetching", () => {
    setupUrqlHooks({ digest: null, fetching: true, status: null });
    const { container } = renderDigestPage(<DigestStartPage />);
    expect(container.querySelector(".digest-kpi-grid")).toBeTruthy();
  });

  it("shows a GraphQL error state", () => {
    setupUrqlHooks({ digest: null, error: new Error("network unreachable") });
    renderDigestPage(<DigestStartPage />);
    expect(screen.getByText("Digest could not be read")).toBeInTheDocument();
  });

  it("renders entrypoint cards", () => {
    setupUrqlHooks({ digest: baseDigest });
    renderDigestPage(<DigestStartPage />);
    const section = screen.getByText("Entrypoints").closest(".surface") as HTMLElement;
    expect(within(section).getByText("run")).toBeInTheDocument();
    expect(within(section).getByText("lib/app.py")).toBeInTheDocument();
  });

  it("renders the annotated repository tree", () => {
    setupUrqlHooks({ digest: baseDigest });
    renderDigestPage(<DigestStartPage />);
    expect(screen.getByText("lib/")).toBeInTheDocument();
    expect(screen.getByText("Core")).toBeInTheDocument();
    // dashboard/ has no dominant domain in the fixture — must show "—", not a guess
    expect(screen.getByText("dashboard/")).toBeInTheDocument();
  });

  it("renders the numbered reading path with reasons", () => {
    setupUrqlHooks({ digest: baseDigest });
    renderDigestPage(<DigestStartPage />);
    expect(screen.getByText("README.md")).toBeInTheDocument();
    expect(screen.getByText(/Repository overview/)).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("shows honest per-section empty states for a partial digest, not a crash", () => {
    setupUrqlHooks({ digest: partialDigest });
    renderDigestPage(<DigestStartPage />);
    expect(screen.getByText(/no discovered run\/develop command names a file/)).toBeInTheDocument();
    expect(screen.getByText(/Not enough evidence/)).toBeInTheDocument();
    expect(screen.getByText("No top-level directory structure available.")).toBeInTheDocument();
  });

  it("shows the page-level empty state when the project map has no indexed files", () => {
    setupUrqlHooks({ digest: { ...baseDigest, footprint: { ...baseDigest.footprint, fileCount: 0 } } });
    renderDigestPage(<DigestStartPage />);
    expect(screen.getByText(/Entrypoints and structure will populate once the repository has content/)).toBeInTheDocument();
  });
});
