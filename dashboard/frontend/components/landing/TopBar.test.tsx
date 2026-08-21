import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { TopBar } from "./TopBar";

describe("TopBar", () => {
  const props = { projectName: "speed-dashboard", branch: "main" };

  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows Good morning between 5 and 11", () => {
    vi.setSystemTime(new Date("2024-01-01T09:00:00"));
    render(<TopBar {...props} />);
    expect(screen.getByText(/Good morning, Sanjay/)).toBeTruthy();
  });

  it("shows Good afternoon between 12 and 17", () => {
    vi.setSystemTime(new Date("2024-01-01T14:00:00"));
    render(<TopBar {...props} />);
    expect(screen.getByText(/Good afternoon, Sanjay/)).toBeTruthy();
  });

  it("shows Good evening from 18 onward and before 5", () => {
    vi.setSystemTime(new Date("2024-01-01T20:00:00"));
    render(<TopBar {...props} />);
    expect(screen.getByText(/Good evening, Sanjay/)).toBeTruthy();
  });

  it("renders project name and branch", () => {
    render(<TopBar {...props} />);
    expect(screen.getByText("speed-dashboard")).toBeTruthy();
    expect(screen.getByText("main")).toBeTruthy();
  });
});
