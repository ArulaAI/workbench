import { describe, it, expect, vi, beforeEach, beforeAll } from "vitest";
import { screen, fireEvent, within } from "@testing-library/react";
import { baseDigest, partialDigest } from "./fixtures";
import { setupUrqlHooks as sharedSetupUrqlHooks, renderDigestPage, type UrqlHookOverrides } from "./testUtils";

beforeAll(() => {
  // jsdom has no ResizeObserver; @xyflow/react requires one.
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/digest/architecture",
}));

vi.mock("urql", () => ({
  useQuery: vi.fn(),
  useMutation: vi.fn(),
  useSubscription: vi.fn(),
  gql: (strings: TemplateStringsArray) => strings.raw.join(""),
}));

import { useQuery, useMutation, useSubscription } from "urql";
import DigestArchitecturePage from "@/app/digest/architecture/page";

const mockedUseQuery = vi.mocked(useQuery);
const mockedUseMutation = vi.mocked(useMutation);
const mockedUseSubscription = vi.mocked(useSubscription);

function setupUrqlHooks(overrides: UrqlHookOverrides = {}) {
  return sharedSetupUrqlHooks(mockedUseQuery, mockedUseMutation, mockedUseSubscription, overrides);
}

describe("DigestArchitecturePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows a loading skeleton while fetching", () => {
    setupUrqlHooks({ digest: null, fetching: true, status: null });
    const { container } = renderDigestPage(<DigestArchitecturePage />);
    expect(container.querySelector(".digest-kpi-grid")).toBeTruthy();
  });

  it("shows a GraphQL error state", () => {
    setupUrqlHooks({ digest: null, error: new Error("network unreachable") });
    renderDigestPage(<DigestArchitecturePage />);
    expect(screen.getByText("Digest could not be read")).toBeInTheDocument();
  });

  it("renders the lane legend with a count per lane", () => {
    setupUrqlHooks({ digest: baseDigest });
    renderDigestPage(<DigestArchitecturePage />);
    expect(screen.getByText("Frontend")).toBeInTheDocument();
    expect(screen.getByText("Services")).toBeInTheDocument();
    expect(screen.getByText("API")).toBeInTheDocument();
    expect(screen.getByText("Data")).toBeInTheDocument();
    expect(screen.getByText("Other")).toBeInTheDocument();
  });

  it("renders a domain node per domain", () => {
    setupUrqlHooks({ digest: baseDigest });
    renderDigestPage(<DigestArchitecturePage />);
    expect(screen.getByTestId("architecture-node-cluster-core")).toBeInTheDocument();
    expect(screen.getByTestId("architecture-node-cluster-ui")).toBeInTheDocument();
  });

  it("shows the verified-evidence note when relationships exist", () => {
    setupUrqlHooks({ digest: baseDigest });
    renderDigestPage(<DigestArchitecturePage />);
    expect(screen.getByText(/All 1 relationship shown is VERIFIED/)).toBeInTheDocument();
  });

  it("shows an honest mixed-evidence note instead of a blanket VERIFIED claim when not every relationship is verified", () => {
    // QA regression: the note must reflect the actual evidenceType values,
    // not assume every relationship is verified just because the current
    // pipeline has never produced anything else.
    const digestWithMixedEvidence = {
      ...baseDigest,
      relationships: [
        { source: "cluster-ui", target: "cluster-core", weight: 12, evidenceType: "verified", sampleReferences: [] },
        { source: "cluster-core", target: "cluster-ui", weight: 2, evidenceType: "unknown", sampleReferences: [] },
      ],
    };
    setupUrqlHooks({ digest: digestWithMixedEvidence });
    renderDigestPage(<DigestArchitecturePage />);
    expect(screen.getByText(/1 of 2 relationships shown is VERIFIED/)).toBeInTheDocument();
    expect(screen.queryByText(/All 2 relationships shown are VERIFIED/)).not.toBeInTheDocument();
  });

  it("selecting a domain node populates the detail panel", () => {
    setupUrqlHooks({ digest: baseDigest });
    renderDigestPage(<DigestArchitecturePage />);
    fireEvent.click(screen.getByTestId("architecture-node-cluster-core"));
    const panel = screen.getByTestId("architecture-detail-panel");
    expect(within(panel).getByText("Core")).toBeInTheDocument();
    expect(within(panel).getByText(/lib\/context\/repository_digest\.py/)).toBeInTheDocument();
  });

  it("associates a risk with a domain via domainId even when its evidence file isn't among the domain's representative files", () => {
    // Regression: domain association used to be `risk.evidence.path in
    // domain.representativeFiles` — representativeFiles is capped at 5,
    // so a risk in a domain's 6th+ file (the overwhelming majority of
    // real domains) was silently invisible on the Architecture screen.
    // The backend now computes domainId from the full CSG cluster
    // membership (the same symbol_to_domain map hotspots already use),
    // so this must work even though the evidence path below is nowhere
    // in cluster-core's representativeFiles.
    const digestWithUnrepresentedFileRisk = {
      ...baseDigest,
      risks: [
        {
          type: "high_blast_radius",
          description: "some_symbol is in the top 1% by blast radius.",
          severity: "high",
          domainId: "cluster-core",
          evidence: [
            { source: "semantic_graph", path: "lib/context/some_other_file.py", line: null, symbol: "some_symbol", artifactKey: null, description: "" },
          ],
        },
      ],
    };
    setupUrqlHooks({ digest: digestWithUnrepresentedFileRisk });
    renderDigestPage(<DigestArchitecturePage />);
    fireEvent.click(screen.getByTestId("architecture-node-cluster-core"));
    const panel = screen.getByTestId("architecture-detail-panel");
    expect(within(panel).getByText(/some_symbol is in the top 1% by blast radius/)).toBeInTheDocument();
  });

  it("does not associate a risk with a domain whose id doesn't match, even if the evidence path coincidentally matches another domain's representative file", () => {
    const digestWithUnrelatedRisk = {
      ...baseDigest,
      risks: [
        {
          type: "high_blast_radius",
          description: "unrelated_symbol risk",
          severity: "high",
          domainId: "cluster-ui",
          evidence: [{ source: "semantic_graph", path: "lib/context/repository_digest.py", line: null, symbol: "unrelated_symbol", artifactKey: null, description: "" }],
        },
      ],
    };
    setupUrqlHooks({ digest: digestWithUnrelatedRisk });
    renderDigestPage(<DigestArchitecturePage />);
    fireEvent.click(screen.getByTestId("architecture-node-cluster-core"));
    const panel = screen.getByTestId("architecture-detail-panel");
    expect(within(panel).queryByText(/unrelated_symbol risk/)).not.toBeInTheDocument();
    expect(within(panel).getByText("No risks are associated with this domain.")).toBeInTheDocument();
  });

  it("shows a placeholder detail panel before any selection", () => {
    setupUrqlHooks({ digest: baseDigest });
    renderDigestPage(<DigestArchitecturePage />);
    expect(screen.getByText("Select a domain in the graph to see its details.")).toBeInTheDocument();
  });

  it("shows an honest empty-relationships state instead of fabricating edges", () => {
    const digestNoRels = { ...baseDigest, relationships: [] };
    setupUrqlHooks({ digest: digestNoRels });
    renderDigestPage(<DigestArchitecturePage />);
    expect(screen.getByText("No cross-domain relationships were found among these domains.")).toBeInTheDocument();
  });

  it("shows a no-domains state when the digest has no domains at all", () => {
    setupUrqlHooks({ digest: { ...baseDigest, domains: [] } });
    renderDigestPage(<DigestArchitecturePage />);
    expect(screen.getByText("No domains discovered yet")).toBeInTheDocument();
  });

  it("handles a partial digest (no domains) without crashing", () => {
    setupUrqlHooks({ digest: partialDigest });
    renderDigestPage(<DigestArchitecturePage />);
    expect(screen.getByText("No domains discovered yet")).toBeInTheDocument();
  });

  it("shows the page-level empty state when the project map has no indexed files", () => {
    setupUrqlHooks({ digest: { ...baseDigest, footprint: { ...baseDigest.footprint, fileCount: 0 } } });
    renderDigestPage(<DigestArchitecturePage />);
    expect(screen.getByText(/The architecture graph will populate once the repository has content/)).toBeInTheDocument();
  });
});
