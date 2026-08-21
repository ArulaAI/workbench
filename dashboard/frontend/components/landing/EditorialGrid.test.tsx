import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { EditorialGrid } from "@/components/landing/EditorialGrid";

describe("EditorialGrid", () => {
  function renderGrid() {
    return render(
      <EditorialGrid
        definePanel={<div>Define content</div>}
        judgePanel={<div>Judge content</div>}
        executePanel={<div>Execute content</div>}
        learnPanel={<div>Learn content</div>}
      />
    );
  }

  it("renders all four panel slots", () => {
    renderGrid();
    expect(screen.getByText("Define content")).toBeInTheDocument();
    expect(screen.getByText("Judge content")).toBeInTheDocument();
    expect(screen.getByText("Execute content")).toBeInTheDocument();
    expect(screen.getByText("Learn content")).toBeInTheDocument();
  });

  it("applies T-shape grid template to the container", () => {
    const { container } = renderGrid();
    const grid = container.firstChild as HTMLElement;
    expect(grid.style.gridTemplateColumns).toBe("260px 1fr 320px");
    expect(grid.style.gridTemplateRows).toBe("1fr 1fr");
  });

  it("sets gap to 16px and padding to 24px on the container", () => {
    const { container } = renderGrid();
    const grid = container.firstChild as HTMLElement;
    expect(grid.style.gap).toBe("16px");
    expect(grid.style.padding).toBe("24px");
  });

  it("sets minimum width to 1280px on the container", () => {
    const { container } = renderGrid();
    const grid = container.firstChild as HTMLElement;
    expect(grid.style.minWidth).toBe("1280px");
  });

  it("places Define panel in column 1 spanning rows 1 to 3", () => {
    renderGrid();
    const cell = screen.getByTestId("editorial-grid-define");
    expect(cell.style.gridColumn).toBe("1");
    expect(cell.style.gridRow).toBe("1 / 3");
  });

  it("places Judge panel in column 2 row 1", () => {
    renderGrid();
    const cell = screen.getByTestId("editorial-grid-judge");
    expect(cell.style.gridColumn).toBe("2");
    expect(cell.style.gridRow).toBe("1");
  });

  it("places Execute panel in column 2 row 2", () => {
    renderGrid();
    const cell = screen.getByTestId("editorial-grid-execute");
    expect(cell.style.gridColumn).toBe("2");
    expect(cell.style.gridRow).toBe("2");
  });

  it("places Learn panel in column 3 spanning rows 1 to 3", () => {
    renderGrid();
    const cell = screen.getByTestId("editorial-grid-learn");
    expect(cell.style.gridColumn).toBe("3");
    expect(cell.style.gridRow).toBe("1 / 3");
  });
});
