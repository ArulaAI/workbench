import { describe, it, expect } from "vitest";
import { statusEquals } from "@/lib/hooks/useRepositoryDigest";
import type { RepositoryDigestBuildStatus } from "@/lib/graphql/queries/repository-digest";

const base: RepositoryDigestBuildStatus = {
  state: "STALE",
  startedAt: null,
  completedAt: "2026-03-15T10:00:00Z",
  lastError: null,
  hasReadableDigest: true,
  hasProjectMap: true,
  indexedGitHead: "abc1234567",
  currentGitHead: "abc1234567",
  staleReasons: [],
};

describe("statusEquals", () => {
  it("treats identical values as equal", () => {
    expect(statusEquals(base, { ...base })).toBe(true);
  });

  it("treats null vs a value as not equal", () => {
    expect(statusEquals(null, base)).toBe(false);
    expect(statusEquals(base, null)).toBe(false);
    expect(statusEquals(null, null)).toBe(true);
  });

  // Max-effort code review regression: an earlier version of this
  // function only compared state/startedAt/completedAt/lastError, so a
  // poll response that changed only one of these fields was silently
  // treated as "no change" and the stale value was kept forever.

  it("detects a currentGitHead change (new commits landed while STALE)", () => {
    const updated = { ...base, currentGitHead: "def7654321" };
    expect(statusEquals(base, updated)).toBe(false);
  });

  it("detects a staleReasons change", () => {
    const updated = { ...base, staleReasons: ["repository head changed"] };
    expect(statusEquals(base, updated)).toBe(false);
  });

  it("detects a hasProjectMap change", () => {
    const updated = { ...base, hasProjectMap: false };
    expect(statusEquals(base, updated)).toBe(false);
  });

  it("detects a hasReadableDigest change", () => {
    const updated = { ...base, hasReadableDigest: false };
    expect(statusEquals(base, updated)).toBe(false);
  });

  it("detects an indexedGitHead change", () => {
    const updated = { ...base, indexedGitHead: "def7654321" };
    expect(statusEquals(base, updated)).toBe(false);
  });

  it("treats different staleReasons arrays with the same length as not equal", () => {
    const a = { ...base, staleReasons: ["a"] };
    const b = { ...base, staleReasons: ["b"] };
    expect(statusEquals(a, b)).toBe(false);
  });

  it("treats equal staleReasons arrays (different references) as equal", () => {
    const a = { ...base, staleReasons: ["same"] };
    const b = { ...base, staleReasons: ["same"] };
    expect(statusEquals(a, b)).toBe(true);
  });
});
