import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { TabClaimBadge, type ClaimState } from "@/components/ceremony/ownership/TabClaimBadge";

describe("TabClaimBadge", () => {
  describe("unclaimed variant", () => {
    it("renders a Claim button", () => {
      render(<TabClaimBadge state={{ kind: "unclaimed" }} />);
      expect(screen.getByRole("button", { name: /claim spec/i })).toBeInTheDocument();
      expect(screen.getByText("Claim")).toBeInTheDocument();
    });

    it("fires onClaim when clicked", () => {
      const onClaim = vi.fn();
      render(<TabClaimBadge state={{ kind: "unclaimed" }} onClaim={onClaim} />);
      fireEvent.click(screen.getByRole("button", { name: /claim spec/i }));
      expect(onClaim).toHaveBeenCalledOnce();
    });

    it("does not fire onClaim while busy", () => {
      const onClaim = vi.fn();
      render(
        <TabClaimBadge
          state={{ kind: "unclaimed" }}
          onClaim={onClaim}
          busy
        />
      );
      const button = screen.getByRole("button", { name: /claim spec/i });
      expect(button).toBeDisabled();
      fireEvent.click(button);
      expect(onClaim).not.toHaveBeenCalled();
    });
  });

  describe("mine variant", () => {
    const state: ClaimState = { kind: "mine", claimant: "Sanjay" };

    it("renders claimant name with accent color via aria-label", () => {
      render(<TabClaimBadge state={state} />);
      expect(screen.getByLabelText("Owned by you")).toBeInTheDocument();
      expect(screen.getByText("Sanjay")).toBeInTheDocument();
    });

    it("renders a Release button that fires onRelease", () => {
      const onRelease = vi.fn();
      render(<TabClaimBadge state={state} onRelease={onRelease} />);
      const release = screen.getByRole("button", { name: /release claim/i });
      fireEvent.click(release);
      expect(onRelease).toHaveBeenCalledOnce();
    });

    it("truncates long claimant names with ellipsis", () => {
      render(
        <TabClaimBadge
          state={{ kind: "mine", claimant: "verylongclaimantname" }}
        />
      );
      // 12-char truncation: first 11 chars + ellipsis
      expect(screen.getByText(/^verylongcla/)).toHaveTextContent("verylongcla…");
    });
  });

  describe("claimed-by-other variant", () => {
    it("renders claimant name with read-only aria-label", () => {
      render(
        <TabClaimBadge
          state={{ kind: "claimed-by-other", claimant: "Priya", committed: false }}
        />
      );
      expect(screen.getByLabelText(/claimed by priya/i)).toBeInTheDocument();
      expect(screen.getByText("Priya")).toBeInTheDocument();
    });

    it("does not render a Claim or Release button", () => {
      render(
        <TabClaimBadge
          state={{ kind: "claimed-by-other", claimant: "Priya", committed: false }}
        />
      );
      expect(screen.queryByRole("button", { name: /claim spec/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /release/i })).not.toBeInTheDocument();
    });
  });

  describe("stale variant", () => {
    const state: ClaimState = {
      kind: "stale",
      claimant: "Priya",
      staleFor: "2h",
    };

    it("renders stale badge duration and Takeover button", () => {
      render(<TabClaimBadge state={state} />);
      expect(screen.getByText("2h")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /take over/i })).toBeInTheDocument();
    });

    it("uses aria-live polite for screen reader announcements", () => {
      render(<TabClaimBadge state={state} />);
      const badge = screen.getByRole("status");
      expect(badge).toHaveAttribute("aria-live", "polite");
    });

    it("fires onClaim when Takeover is clicked", () => {
      const onClaim = vi.fn();
      render(<TabClaimBadge state={state} onClaim={onClaim} />);
      fireEvent.click(screen.getByRole("button", { name: /take over/i }));
      expect(onClaim).toHaveBeenCalledOnce();
    });
  });

  describe("committed variant", () => {
    it("renders static claimant name", () => {
      render(
        <TabClaimBadge
          state={{ kind: "committed", claimant: "Sanjay", ratified: false }}
        />
      );
      expect(screen.getByLabelText(/committed by sanjay/i)).toBeInTheDocument();
      expect(screen.getByText("Sanjay")).toBeInTheDocument();
    });

    it("includes ratified flag in aria-label when ratified", () => {
      render(
        <TabClaimBadge
          state={{ kind: "committed", claimant: "Sanjay", ratified: true }}
        />
      );
      expect(screen.getByLabelText(/ratified/i)).toBeInTheDocument();
    });
  });
});
