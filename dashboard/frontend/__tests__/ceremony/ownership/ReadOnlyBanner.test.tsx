import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { ReadOnlyBanner } from "@/components/ceremony/ownership/ReadOnlyBanner";

describe("ReadOnlyBanner", () => {
  describe("standard variant", () => {
    it("renders 'Read-only · claimed by {name}' text", () => {
      render(<ReadOnlyBanner kind="standard" claimant="Sanjay" />);
      expect(screen.getByText(/read-only/i)).toBeInTheDocument();
      expect(screen.getByText("Sanjay")).toBeInTheDocument();
    });

    it("has polite aria-live for screen reader announcements", () => {
      render(<ReadOnlyBanner kind="standard" claimant="Sanjay" />);
      const status = screen.getByRole("status");
      expect(status).toHaveAttribute("aria-live", "polite");
    });

    it("does not render a takeover button in standard kind", () => {
      render(<ReadOnlyBanner kind="standard" claimant="Sanjay" />);
      expect(
        screen.queryByRole("button", { name: /take over/i })
      ).not.toBeInTheDocument();
    });
  });

  describe("stale variant", () => {
    it("renders the inactive message with duration", () => {
      render(
        <ReadOnlyBanner
          kind="stale"
          claimant="Priya"
          staleFor="2h"
          onTakeover={() => {}}
        />
      );
      expect(screen.getByText("Priya")).toBeInTheDocument();
      expect(screen.getByText(/has been inactive/i)).toBeInTheDocument();
      expect(screen.getByText(/2h/)).toBeInTheDocument();
    });

    it("renders a takeover button that fires onTakeover", () => {
      const onTakeover = vi.fn();
      render(
        <ReadOnlyBanner
          kind="stale"
          claimant="Priya"
          staleFor="2h"
          onTakeover={onTakeover}
        />
      );
      const button = screen.getByRole("button", { name: /take over/i });
      fireEvent.click(button);
      expect(onTakeover).toHaveBeenCalledOnce();
    });

    it("omits takeover affordance when onTakeover is not provided", () => {
      render(<ReadOnlyBanner kind="stale" claimant="Priya" staleFor="2h" />);
      expect(
        screen.queryByRole("button", { name: /take over/i })
      ).not.toBeInTheDocument();
    });
  });
});
