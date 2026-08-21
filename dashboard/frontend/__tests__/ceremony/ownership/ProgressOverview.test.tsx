import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";

import { ProgressOverview } from "@/components/ceremony/ownership/ProgressOverview";
import type { ProgressRowData } from "@/components/ceremony/ownership/ProgressRow";

const mine: ProgressRowData = {
  specType: "prd",
  claimant: "Sanjay",
  claimantStatus: "active",
  validation: "pass",
  validationWarnings: 0,
  suggestionsOpen: 0,
  status: "drafting",
};

const other: ProgressRowData = {
  specType: "design",
  claimant: "Priya",
  claimantStatus: "active",
  validation: "warn",
  validationWarnings: 3,
  suggestionsOpen: 2,
  status: "committed",
};

const unclaimed: ProgressRowData = {
  specType: "rfc",
  claimant: null,
  claimantStatus: "unclaimed",
  validation: "pending",
  validationWarnings: 0,
  suggestionsOpen: 0,
  status: "drafting",
};

const ratified: ProgressRowData = {
  specType: "rfc-ingestion",
  claimant: "Alex",
  claimantStatus: "active",
  validation: "pass",
  validationWarnings: 0,
  suggestionsOpen: 0,
  status: "ratified",
};

const noop = () => {};

describe("ProgressOverview", () => {
  describe("empty state", () => {
    it("renders the empty-state message when rows is empty", () => {
      render(
        <ProgressOverview
          rows={[]}
          activeSpecType="prd"
          onRowClick={noop}
        />
      );
      expect(screen.getByText(/No specs drafted yet/)).toBeInTheDocument();
    });

    it("does not render any row buttons when empty", () => {
      const onClick = vi.fn();
      render(
        <ProgressOverview
          rows={[]}
          activeSpecType="prd"
          onRowClick={onClick}
        />
      );
      expect(screen.queryAllByRole("button")).toHaveLength(0);
    });
  });

  describe("populated state", () => {
    it("renders one row per spec_type", () => {
      render(
        <ProgressOverview
          rows={[mine, other, unclaimed]}
          activeSpecType="prd"
          onRowClick={noop}
          defaultOpen={true}
        />
      );
      expect(screen.getByText("PRD")).toBeInTheDocument();
      expect(screen.getByText("Design")).toBeInTheDocument();
      expect(screen.getByText("RFC")).toBeInTheDocument();
    });

    it("formats child RFC slot labels as 'RFC: {slug}'", () => {
      render(
        <ProgressOverview
          rows={[ratified]}
          activeSpecType="rfc-ingestion"
          onRowClick={noop}
          defaultOpen={true}
        />
      );
      expect(screen.getByText("RFC: ingestion")).toBeInTheDocument();
    });

    it("fires onRowClick with the correct spec_type when a row is clicked", () => {
      const onClick = vi.fn();
      render(
        <ProgressOverview
          rows={[mine, other]}
          activeSpecType="prd"
          onRowClick={onClick}
          defaultOpen={true}
        />
      );
      const designRow = screen.getByRole("button", {
        name: /design, priya, committed/i,
      });
      fireEvent.click(designRow);
      expect(onClick).toHaveBeenCalledWith("design");
    });

    it("shows 'unclaimed' in italic for rows with no claimant", () => {
      render(
        <ProgressOverview
          rows={[unclaimed]}
          activeSpecType="rfc"
          onRowClick={noop}
          defaultOpen={true}
        />
      );
      expect(screen.getByText("unclaimed")).toBeInTheDocument();
    });

    it("renders suggestion count when non-zero", () => {
      render(
        <ProgressOverview
          rows={[other]}
          activeSpecType="prd"
          onRowClick={noop}
          defaultOpen={true}
        />
      );
      expect(screen.getByText("2")).toBeInTheDocument();
    });

    it("omits suggestion count when zero", () => {
      render(
        <ProgressOverview
          rows={[mine]}
          activeSpecType="prd"
          onRowClick={noop}
          defaultOpen={true}
        />
      );
      // mine has suggestionsOpen: 0
      const row = screen.getByRole("button", {
        name: /prd, sanjay, drafting/i,
      });
      // The suggestion pill (red bg) should not be in the row
      const pill = within(row).queryByText("0");
      expect(pill).not.toBeInTheDocument();
    });
  });

  describe("summary line", () => {
    it("shows committed and ratified counts", () => {
      render(
        <ProgressOverview
          rows={[mine, other, ratified]}
          activeSpecType="prd"
          onRowClick={noop}
          defaultOpen={true}
        />
      );
      // Summary text splits across <strong> tags; test the surrounding text
      // via the ARIA region match.
      const region = screen.getByRole("region", { name: /ceremony progress/i });
      // mine: drafting, other: committed, ratified: ratified
      // committedCount counts committed + ratified (ratified implies
      // committed), so expected summary: "2 of 3 committed · 1 of 3 ratified".
      expect(region).toHaveTextContent(/2\s*of\s*3\s*committed/);
      expect(region).toHaveTextContent(/1\s*of\s*3\s*ratified/);
    });
  });

  describe("collapse behavior", () => {
    it("defaults to collapsed when rows.length <= 3 and no override", () => {
      render(
        <ProgressOverview
          rows={[mine, other, unclaimed]}
          activeSpecType="prd"
          onRowClick={noop}
        />
      );
      // Rows should not be visible; only the header button + chevron.
      expect(screen.queryByText("Design")).not.toBeInTheDocument();
    });

    it("defaults to open when rows.length > 3", () => {
      render(
        <ProgressOverview
          rows={[mine, other, unclaimed, ratified]}
          activeSpecType="prd"
          onRowClick={noop}
        />
      );
      expect(screen.getByText("Design")).toBeInTheDocument();
    });

    it("toggles open/closed when header is clicked", () => {
      render(
        <ProgressOverview
          rows={[mine, other]}
          activeSpecType="prd"
          onRowClick={noop}
          defaultOpen={false}
        />
      );
      expect(screen.queryByText("Design")).not.toBeInTheDocument();

      const header = screen.getByRole("button", { name: /progress/i });
      fireEvent.click(header);
      expect(screen.getByText("Design")).toBeInTheDocument();

      fireEvent.click(header);
      expect(screen.queryByText("Design")).not.toBeInTheDocument();
    });
  });
});
