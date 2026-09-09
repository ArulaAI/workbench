import { act, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { GenerationProgress } from "./GenerationProgress";
import type { Operation } from "./types";

afterEach(() => vi.useRealTimers());

it("shows persisted elapsed time on return and explains a long wait without invented percentages", () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-09-09T16:23:05Z"));
  const operation: Operation = {id:"op",kind:"prd",status:"running",text:"Generate",error:null,version_id:null,
    created_at:"2026-09-09T16:20:00Z",started_at:"2026-09-09T16:20:35Z",timeout_seconds:360};
  const {rerender,unmount} = render(<GenerationProgress operation={operation} />);
  expect(screen.getByText("Elapsed: 2:30")).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("still waiting for the complete response");
  expect(screen.getByText(/Model response limit: 6 min/)).toBeInTheDocument();
  act(() => vi.advanceTimersByTime(1000));
  expect(screen.getByText("Elapsed: 2:31")).toBeInTheDocument();
  rerender(<GenerationProgress operation={{...operation,id:"retry",status:"queued",started_at:undefined,created_at:new Date().toISOString()}} />);
  expect(screen.getByText("Time in queue: 0:00")).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("Waiting for an available generation slot");
  expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  unmount();
  expect(vi.getTimerCount()).toBe(0);
});

it("keeps older operations readable when timing metadata is unavailable", () => {
  render(<GenerationProgress operation={{id:"old",kind:"rfc",status:"running",text:"Generate",error:null,version_id:null}} />);
  expect(screen.getByRole("status")).toHaveTextContent("complete draft can take several minutes");
  expect(screen.queryByText(/Elapsed:/)).not.toBeInTheDocument();
});
