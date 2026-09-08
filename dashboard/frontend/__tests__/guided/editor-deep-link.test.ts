import { describe, expect, it } from "vitest";
import {
  editorPathFromSearch,
  specTypeForPath,
  toRelativeSpecPath,
} from "@/lib/editor-path";

describe("editor deep links", () => {
  it("opens a generated guided PRD from the path query parameter", () => {
    expect(
      editorPathFromSearch("?path=specs%2Fdue-dates-for-tasks%2Fprd.md"),
    ).toBe("specs/due-dates-for-tasks/prd.md");
    expect(specTypeForPath("specs/due-dates-for-tasks/prd.md")).toBe("prd");
  });

  it("normalizes absolute project paths", () => {
    expect(
      toRelativeSpecPath("/workspace/project/specs/due-dates-for-tasks/prd.md"),
    ).toBe("specs/due-dates-for-tasks/prd.md");
  });

  it("rejects paths outside the specs directory", () => {
    expect(editorPathFromSearch("?path=.env")).toBeNull();
    expect(editorPathFromSearch("?path=specs%2F..%2F.env.md")).toBeNull();
  });
});
