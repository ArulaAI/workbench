import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusBar } from "./StatusBar";

describe("StatusBar", () => {
  const baseProps = {
    projectName: "my-project",
    featureCount: 4,
    runningCount: 0,
    connected: true,
  };

  it("shows Connected with green dot when connected is true", () => {
    render(<StatusBar {...baseProps} connected={true} />);
    expect(screen.getByText("Connected")).toBeDefined();
    expect(screen.queryByText("Disconnected")).toBeNull();
  });

  it("shows Disconnected with red dot when connected is false", () => {
    render(<StatusBar {...baseProps} connected={false} />);
    expect(screen.getByText("Disconnected")).toBeDefined();
    expect(screen.queryByText("Connected")).toBeNull();
  });

  it("renders project name", () => {
    render(<StatusBar {...baseProps} projectName="acme-corp" />);
    expect(screen.getByText("acme-corp")).toBeDefined();
  });

  it("renders feature count", () => {
    render(<StatusBar {...baseProps} featureCount={7} />);
    expect(screen.getByText("7 features")).toBeDefined();
  });

  it("renders running count text", () => {
    render(<StatusBar {...baseProps} runningCount={3} />);
    expect(screen.getByText("3 running")).toBeDefined();
  });

  it("shows accent dot when runningCount is greater than 0", () => {
    const { container } = render(<StatusBar {...baseProps} runningCount={2} />);
    const accentDots = container.querySelectorAll(".animate-pulse");
    expect(accentDots.length).toBeGreaterThan(0);
  });

  it("hides accent dot when runningCount is 0", () => {
    const { container } = render(<StatusBar {...baseProps} runningCount={0} />);
    const accentDots = container.querySelectorAll(".animate-pulse");
    expect(accentDots.length).toBe(0);
  });
});
