import { describe, expect, it } from "vitest";
import { deriveSlug, isValidSlug } from "@/lib/graphql/queries/authoring";

describe("deriveSlug", () => {
  it("mirrors the helper's normalisation rules", () => {
    expect(deriveSlug("Due dates for tasks")).toBe("due-dates-for-tasks");
    expect(deriveSlug("  Overdue  filtering!  ")).toBe("overdue-filtering");
    expect(deriveSlug("Q3 / 2026 rollout")).toBe("q3-2026-rollout");
    expect(deriveSlug("---")).toBe("");
  });

  it("caps the slug at 50 characters without a trailing hyphen", () => {
    const slug = deriveSlug("a".repeat(48) + " b c");
    expect(slug.length).toBeLessThanOrEqual(50);
    expect(slug.endsWith("-")).toBe(false);
  });
});

describe("isValidSlug", () => {
  it("accepts what the helper accepts", () => {
    expect(isValidSlug("due-dates-for-tasks")).toBe(true);
    expect(isValidSlug("a")).toBe(true);
  });

  it("rejects what the helper rejects", () => {
    expect(isValidSlug("-leading")).toBe(false);
    expect(isValidSlug("trailing-")).toBe(false);
    expect(isValidSlug("double--hyphen")).toBe(false);
    expect(isValidSlug("Upper")).toBe(false);
    expect(isValidSlug("a".repeat(51))).toBe(false);
  });
});
