import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, within } from "@testing-library/react";
import { baseDigest, partialDigest } from "./fixtures";
import { setupUrqlHooks as sharedSetupUrqlHooks, renderDigestPage, type UrqlHookOverrides } from "./testUtils";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/digest/security",
}));

vi.mock("urql", () => ({
  useQuery: vi.fn(),
  useMutation: vi.fn(),
  useSubscription: vi.fn(),
  gql: (strings: TemplateStringsArray) => strings.raw.join(""),
}));

import { useQuery, useMutation, useSubscription } from "urql";
import DigestSecurityPage from "@/app/digest/security/page";

const mockedUseQuery = vi.mocked(useQuery);
const mockedUseMutation = vi.mocked(useMutation);
const mockedUseSubscription = vi.mocked(useSubscription);

function setupUrqlHooks(overrides: UrqlHookOverrides = {}) {
  return sharedSetupUrqlHooks(mockedUseQuery, mockedUseMutation, mockedUseSubscription, overrides);
}

describe("DigestSecurityPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows a loading skeleton while fetching", () => {
    setupUrqlHooks({ digest: null, fetching: true, status: null });
    const { container } = renderDigestPage(<DigestSecurityPage />);
    expect(container.querySelector(".digest-kpi-grid")).toBeTruthy();
  });

  it("shows a GraphQL error state", () => {
    setupUrqlHooks({ digest: null, error: new Error("network unreachable") });
    renderDigestPage(<DigestSecurityPage />);
    expect(screen.getByText("Digest could not be read")).toBeInTheDocument();
  });

  it("renders secret indicators with redaction badges, never a raw value", () => {
    setupUrqlHooks({ digest: baseDigest });
    renderDigestPage(<DigestSecurityPage />);
    expect(screen.getByText("OPENAI_API_KEY")).toBeInTheDocument();
    expect(screen.getByText("AWS_KEY")).toBeInTheDocument();
    expect(screen.getByText("aws_access_key_id")).toBeInTheDocument();
    expect(screen.getAllByText("redacted").length).toBeGreaterThan(0);
    // The fixture never contains a raw secret value, but assert the page
    // doesn't render anything shaped like one regardless of fixture content.
    expect(screen.queryByText(/AKIA[0-9A-Z]{16}/)).not.toBeInTheDocument();
  });

  it("renders sensitive configuration findings with severity", () => {
    setupUrqlHooks({ digest: baseDigest });
    renderDigestPage(<DigestSecurityPage />);
    expect(screen.getByText("TLS certificate verification appears to be disabled")).toBeInTheDocument();
    expect(screen.getByText("high")).toBeInTheDocument();
  });

  it("renders authentication indicators and detected security tooling", () => {
    setupUrqlHooks({ digest: baseDigest });
    renderDigestPage(<DigestSecurityPage />);
    expect(screen.getByText(/flask-login/)).toBeInTheDocument();
    expect(screen.getByText("SECURITY.md")).toBeInTheDocument();
  });

  it("shows an honest unavailable state when security is null", () => {
    setupUrqlHooks({ digest: { ...baseDigest, security: null } });
    renderDigestPage(<DigestSecurityPage />);
    expect(screen.getByText(/Security information isn.t available/)).toBeInTheDocument();
  });

  it("shows the no-findings empty state, never fake findings, when every category is empty", () => {
    setupUrqlHooks({
      digest: {
        ...baseDigest,
        security: { secretIndicators: [], sensitiveConfiguration: [], authenticationIndicators: [], securityToolingDetected: [] },
      },
    });
    renderDigestPage(<DigestSecurityPage />);
    expect(screen.getByText("No security findings were discovered from supported repository evidence.")).toBeInTheDocument();
  });

  it("shows an unknown-severity label instead of inventing one", () => {
    setupUrqlHooks({
      digest: {
        ...baseDigest,
        security: {
          secretIndicators: [],
          sensitiveConfiguration: [
            { category: "x", title: "Some finding", description: "desc", severity: null, file: "a.py", line: 1, evidence: [] },
          ],
          authenticationIndicators: [],
          securityToolingDetected: [],
        },
      },
    });
    renderDigestPage(<DigestSecurityPage />);
    const section = screen.getByText("Some finding").closest("div") as HTMLElement;
    expect(within(section).getByText("severity unknown")).toBeInTheDocument();
  });

  it("handles a partial digest without crashing", () => {
    setupUrqlHooks({ digest: partialDigest });
    renderDigestPage(<DigestSecurityPage />);
    expect(screen.getByText(/Security information isn.t available/)).toBeInTheDocument();
  });

  it("shows the page-level empty state when the project map has no indexed files", () => {
    setupUrqlHooks({ digest: { ...baseDigest, footprint: { ...baseDigest.footprint, fileCount: 0 } } });
    renderDigestPage(<DigestSecurityPage />);
    expect(screen.getByText(/Security information will populate once the repository has content/)).toBeInTheDocument();
  });
});
