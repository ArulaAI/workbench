import { describe, expect, it } from "vitest";
import type { DraftView } from "@/lib/graphql/queries/feature-defects";
import { canFileDefectDraft } from "./defect-draft";

const complete: DraftView["draft"] = {
  title: "Retry helper has no tests",
  severity: "P2",
  severity_confirmed: true,
  related_features: ["payments"],
  observed: "The test calls refund directly.",
  expected: "The test exercises the helper.",
  reproduction: "1. Open the helper.\n2. Inspect the test.",
  reproducibility: "always",
  last_known_working: "Unknown; the helper is new.",
  environment: "Node 22 on the fixture branch.",
  error_output: "No error output; this is a coverage gap.",
  context: "Review task 1.",
};

describe("canFileDefectDraft", () => {
  it("blocks missing required fields and unnumbered reproduction", () => {
    expect(canFileDefectDraft(complete, "Track tests", 0, "")).toBe(true);
    for (const field of ["title", "observed", "expected", "reproducibility", "last_known_working", "environment", "error_output", "context"] as const) {
      expect(canFileDefectDraft({ ...complete, [field]: "" }, "Track tests", 0, "")).toBe(false);
    }
    expect(canFileDefectDraft({ ...complete, reproduction: "Run the test" }, "Track tests", 0, "")).toBe(false);
    expect(canFileDefectDraft(complete, "", 0, "")).toBe(false);
    expect(canFileDefectDraft(complete, "Track tests", 1, "")).toBe(false);
  });
});
