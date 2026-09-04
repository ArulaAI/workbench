import { describe, it, expect, beforeAll, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ArchitectureGraph, layoutArchitectureGraph, LANE_ORDER } from "@/components/digest/ArchitectureGraph";
import type { DigestDomain, DigestRelationship } from "@/lib/graphql/queries/repository-digest";

beforeAll(() => {
  // jsdom has no ResizeObserver; @xyflow/react requires one.
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

function domain(id: string, lane: DigestDomain["lane"], overrides: Partial<DigestDomain> = {}): DigestDomain {
  return {
    id, label: id, summary: "", confidence: "DERIVED", fileCount: 1, symbolCount: 1,
    representativeFiles: [], representativeSymbols: [], dependsOn: [], usedBy: [], evidence: [],
    lane, ...overrides,
  };
}

function relationship(source: string, target: string, weight = 1): DigestRelationship {
  return { source, target, weight, evidenceType: "verified", sampleReferences: [] };
}

describe("layoutArchitectureGraph", () => {
  it("groups nodes by lane in a fixed lane order regardless of input order", () => {
    const domains = [domain("b1", "data"), domain("a1", "frontend"), domain("c1", "services")];
    const { nodes } = layoutArchitectureGraph(domains, [], null);
    const laneOf = (id: string) => nodes.find((n) => n.id === id)!.position.x;
    expect(laneOf("a1")).toBeLessThan(laneOf("c1"));
    expect(laneOf("c1")).toBeLessThan(laneOf("b1"));
  });

  it("produces identical node positions for the same input regardless of array order", () => {
    const domains1 = [domain("x", "api"), domain("y", "api")];
    const domains2 = [domain("y", "api"), domain("x", "api")];
    const layout1 = layoutArchitectureGraph(domains1, [], null);
    const layout2 = layoutArchitectureGraph(domains2, [], null);
    const posById = (nodes: typeof layout1.nodes) => Object.fromEntries(nodes.map((n) => [n.id, n.position]));
    expect(posById(layout1.nodes)).toEqual(posById(layout2.nodes));
  });

  it("sorts edges deterministically by source->target regardless of input order", () => {
    const domains = [domain("a", "api"), domain("b", "api"), domain("c", "api")];
    const rels1 = [relationship("c", "a"), relationship("a", "b")];
    const rels2 = [relationship("a", "b"), relationship("c", "a")];
    const e1 = layoutArchitectureGraph(domains, rels1, null).edges.map((e) => e.id);
    const e2 = layoutArchitectureGraph(domains, rels2, null).edges.map((e) => e.id);
    expect(e1).toEqual(e2);
  });

  it("drops relationships that reference a domain not in the node set", () => {
    const domains = [domain("a", "api")];
    const rels = [relationship("a", "does-not-exist")];
    const { edges } = layoutArchitectureGraph(domains, rels, null);
    expect(edges).toHaveLength(0);
  });

  it("marks the selected node's data.isSelected", () => {
    const domains = [domain("a", "api"), domain("b", "api")];
    const { nodes } = layoutArchitectureGraph(domains, [], "b");
    expect((nodes.find((n) => n.id === "a")!.data as any).isSelected).toBe(false);
    expect((nodes.find((n) => n.id === "b")!.data as any).isSelected).toBe(true);
  });

  it("covers every lane in LANE_ORDER", () => {
    expect(LANE_ORDER).toEqual(["frontend", "api", "services", "data", "other"]);
  });
});

describe("ArchitectureGraph component", () => {
  it("renders a node per domain", () => {
    render(
      <ArchitectureGraph
        domains={[domain("c1", "services", { label: "Core" })]}
        relationships={[]}
        selectedId={null}
        onSelectDomain={() => {}}
      />
    );
    expect(screen.getByTestId("architecture-node-c1")).toBeInTheDocument();
    expect(screen.getByText("Core")).toBeInTheDocument();
  });

  it("calls onSelectDomain when a node is clicked", () => {
    const onSelect = vi.fn();
    render(
      <ArchitectureGraph
        domains={[domain("c1", "services", { label: "Core" })]}
        relationships={[]}
        selectedId={null}
        onSelectDomain={onSelect}
      />
    );
    fireEvent.click(screen.getByTestId("architecture-node-c1"));
    expect(onSelect).toHaveBeenCalledWith("c1");
  });
});
