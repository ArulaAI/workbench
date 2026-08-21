import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { CommitBar } from "@/components/ceremony/CommitBar";
import type { ClaimState } from "@/components/ceremony/ownership";
import type { ValidationState } from "@/lib/graphql/queries/ceremony";

const passingValidation: ValidationState = {
  dimensions: [],
  passCount: 3,
  warnCount: 0,
  failCount: 0,
};

const failingValidation: ValidationState = {
  dimensions: [],
  passCount: 0,
  warnCount: 0,
  failCount: 2,
};

const noop = () => {};

describe("CommitBar", () => {
  describe("claimant modes", () => {
    const mine: ClaimState = { kind: "mine", claimant: "Sanjay" };

    it("renders an enabled Commit button when viewer is claimant and validation passes", () => {
      const onCommit = vi.fn();
      render(
        <CommitBar
          activeSpecType="prd"
          claimState={mine}
          validationState={passingValidation}
          unresolvedSuggestionCount={0}
          resolvedSuggestionCount={0}
          onCommit={onCommit}
        />
      );
      const button = screen.getByRole("button", { name: /commit prd/i });
      expect(button).not.toBeDisabled();
      fireEvent.click(button);
      expect(onCommit).toHaveBeenCalledOnce();
    });

    it("disables the Commit button when validation has failures", () => {
      render(
        <CommitBar
          activeSpecType="prd"
          claimState={mine}
          validationState={failingValidation}
          unresolvedSuggestionCount={0}
          resolvedSuggestionCount={0}
          onCommit={noop}
        />
      );
      const button = screen.getByRole("button", { name: /commit prd/i });
      expect(button).toBeDisabled();
      expect(screen.getByText(/Resolve .*fail/i)).toBeInTheDocument();
    });

    it("disables the Commit button when unresolved suggestions exist", () => {
      render(
        <CommitBar
          activeSpecType="design"
          claimState={mine}
          validationState={passingValidation}
          unresolvedSuggestionCount={3}
          resolvedSuggestionCount={2}
          onCommit={noop}
        />
      );
      const button = screen.getByRole("button", { name: /commit design/i });
      expect(button).toBeDisabled();
      expect(screen.getByText(/3 pending suggestion/i)).toBeInTheDocument();
    });
  });

  describe("non-claimant modes", () => {
    it("disables Commit and shows 'Claimed by {name}' caption for claimed-by-other", () => {
      render(
        <CommitBar
          activeSpecType="prd"
          claimState={{
            kind: "claimed-by-other",
            claimant: "Priya",
            committed: false,
          }}
          validationState={passingValidation}
          unresolvedSuggestionCount={0}
          resolvedSuggestionCount={0}
          onCommit={noop}
        />
      );
      const button = screen.getByRole("button", {
        name: /commit prd, disabled .*claimed by priya/i,
      });
      expect(button).toBeDisabled();
      expect(screen.getByText(/Claimed by Priya/i)).toBeInTheDocument();
    });

    it("shows 'Claim stale' caption for stale variant", () => {
      render(
        <CommitBar
          activeSpecType="rfc"
          claimState={{ kind: "stale", claimant: "Priya", staleFor: "3h" }}
          validationState={passingValidation}
          unresolvedSuggestionCount={0}
          resolvedSuggestionCount={0}
          onCommit={noop}
        />
      );
      const button = screen.getByRole("button", { name: /commit rfc/i });
      expect(button).toBeDisabled();
      expect(screen.getByText(/Claim stale/i)).toBeInTheDocument();
      expect(screen.getByText(/Priya inactive/i)).toBeInTheDocument();
    });

    it("shows 'Committed by {name}' caption for committed variant", () => {
      render(
        <CommitBar
          activeSpecType="prd"
          claimState={{ kind: "committed", claimant: "Sanjay", ratified: false }}
          validationState={passingValidation}
          unresolvedSuggestionCount={0}
          resolvedSuggestionCount={0}
          onCommit={noop}
        />
      );
      expect(screen.getByText(/Committed by Sanjay/i)).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: /commit prd, disabled/i })
      ).toBeDisabled();
    });
  });

  describe("unclaimed mode", () => {
    it("disables Commit and prompts to claim first", () => {
      render(
        <CommitBar
          activeSpecType="design"
          claimState={{ kind: "unclaimed" }}
          validationState={passingValidation}
          unresolvedSuggestionCount={0}
          resolvedSuggestionCount={0}
          onCommit={noop}
        />
      );
      const button = screen.getByRole("button", { name: /commit design/i });
      expect(button).toBeDisabled();
      expect(screen.getByText(/Claim Design first/i)).toBeInTheDocument();
    });
  });

  describe("scope label", () => {
    it("renders the active spec type label", () => {
      render(
        <CommitBar
          activeSpecType="rfc-ingestion"
          claimState={{ kind: "mine", claimant: "Sanjay" }}
          validationState={passingValidation}
          unresolvedSuggestionCount={0}
          resolvedSuggestionCount={0}
          onCommit={noop}
        />
      );
      expect(screen.getByText(/SCOPE/)).toBeInTheDocument();
      expect(screen.getByText(/RFC: ingestion/)).toBeInTheDocument();
    });
  });
});
