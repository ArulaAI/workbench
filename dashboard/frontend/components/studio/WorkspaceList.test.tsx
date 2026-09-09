import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { WorkspaceList } from "./WorkspaceList";
import type { Feature } from "./types";

function feature(id = "feature-1", title = "Saved views"): Feature {
  const doc = {head:null,published:null,versions:[],snapshot:null,stale:[],blockers:[]};
  return {id,title,brief:"Save personal filters.",context:"",revision:3,updated_at:"now",operations:[],comments:[],messages:[],documents:{prd:doc,design:doc,rfc:doc}};
}

function setup(initial = [feature()]) {
  const open = vi.fn();
  function Harness() {
    const [features, setFeatures] = useState(initial);
    return <WorkspaceList features={features} onOpen={open} onDeleted={id => setFeatures(current => current.filter(f => f.id !== id))} onRefresh={async () => setFeatures(current => current.map(f => ({...f,revision:4})))} />;
  }
  render(<Harness />);
  return open;
}

afterEach(() => vi.unstubAllGlobals());

describe("Workspace deletion", () => {
  it("opens a confirmation without navigating and lets the user cancel or press Escape", () => {
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    const open = setup();
    const trigger = screen.getByRole("button", {name:"Delete workspace: Saved views"});
    trigger.focus(); fireEvent.click(trigger);
    const dialog = screen.getByRole("alertdialog", {name:"Delete workspace?"});
    expect(dialog).toHaveAccessibleDescription(/all versions, chat, and comments/);
    expect(within(dialog).getByText("Saved views")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", {name:"Cancel"}));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    fireEvent.click(trigger); fireEvent.keyDown(document, {key:"Escape"});
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
    expect(open).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", {name:"Open workspace: Saved views"}));
    expect(open).toHaveBeenCalledWith("feature-1", "prd");
  });

  it("removes only the confirmed workspace, updates the count and restores keyboard focus", async () => {
    const fetch = vi.fn(async () => ({ok:true,json:async () => ({deleted:true})}));
    vi.stubGlobal("fetch", fetch);
    setup([feature(),feature("feature-2","Task dates")]);
    fireEvent.click(screen.getByRole("button", {name:"Delete workspace: Saved views"}));
    fireEvent.click(screen.getByRole("button", {name:"Delete workspace",exact:true}));
    await screen.findByRole("status");
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/features/feature-1"), expect.objectContaining({method:"DELETE",body:JSON.stringify({expected_revision:3})}));
    expect(screen.queryByRole("button", {name:"Open workspace: Saved views"})).not.toBeInTheDocument();
    expect(screen.getByRole("button", {name:"Open workspace: Task dates"})).toBeInTheDocument();
    expect(screen.getByRole("heading", {name:"Your feature workspaces 1"})).toHaveFocus();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("shows the empty state after deleting the last workspace", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ok:true,json:async () => ({deleted:true})})));
    setup();
    fireEvent.click(screen.getByRole("button", {name:"Delete workspace: Saved views"}));
    fireEvent.click(screen.getByRole("button", {name:"Delete workspace",exact:true}));
    await screen.findByText(/Your features will appear here/);
    expect(screen.getByRole("heading", {name:"Your feature workspaces 0"})).toBeInTheDocument();
  });

  it("keeps the workspace on a conflict and uses a fresh revision only after reopening confirmation", async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce({ok:false,json:async () => ({detail:"This workspace changed. Close this dialog and review the latest workspace before deleting it."})})
      .mockResolvedValueOnce({ok:true,json:async () => ({deleted:true})});
    vi.stubGlobal("fetch", fetch); setup();
    fireEvent.click(screen.getByRole("button", {name:"Delete workspace: Saved views"}));
    fireEvent.click(screen.getByRole("button", {name:"Delete workspace",exact:true}));
    expect(await screen.findByRole("alert")).toHaveTextContent("This workspace changed");
    expect(screen.getByRole("button", {name:"Open workspace: Saved views"})).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", {name:"Cancel"})).toBeEnabled());
    fireEvent.click(screen.getByRole("button", {name:"Cancel"}));
    fireEvent.click(screen.getByRole("button", {name:"Delete workspace: Saved views"}));
    fireEvent.click(screen.getByRole("button", {name:"Delete workspace",exact:true}));
    await screen.findByRole("status");
    expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({expected_revision:4});
  });

  it("keeps confirmation open on a network failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Connection lost"))); setup();
    fireEvent.click(screen.getByRole("button", {name:"Delete workspace: Saved views"}));
    fireEvent.click(screen.getByRole("button", {name:"Delete workspace",exact:true}));
    expect(await screen.findByRole("alert")).toHaveTextContent("Connection lost");
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(screen.getByRole("button", {name:"Open workspace: Saved views"})).toBeInTheDocument();
  });

  it("prevents duplicate submissions and dismissal while deletion is pending", async () => {
    let complete!: (value: unknown) => void;
    const fetch = vi.fn(() => new Promise(resolve => {complete = resolve;}));
    vi.stubGlobal("fetch", fetch); setup();
    fireEvent.click(screen.getByRole("button", {name:"Delete workspace: Saved views"}));
    const confirm = screen.getByRole("button", {name:"Delete workspace",exact:true});
    fireEvent.click(confirm); fireEvent.click(confirm);
    expect(confirm).toBeDisabled();
    expect(screen.getByRole("button", {name:"Cancel"})).toBeDisabled();
    fireEvent.keyDown(document, {key:"Escape"});
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(1);
    complete({ok:true,json:async () => ({deleted:true})});
    await screen.findByRole("status");
  });
});
