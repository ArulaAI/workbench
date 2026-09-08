import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import Studio from "./Studio";
import { SectionEditor } from "./Editors";
import type { Feature, Section, Snapshot } from "./types";

vi.mock("@/components/landing/IconRail", () => ({IconRail: () => null}));
vi.mock("next/link", () => ({default: ({children, href, ...props}: React.AnchorHTMLAttributes<HTMLAnchorElement>) => <a href={href} {...props}>{children}</a>}));

const section: Section = {id:"scope", title:"Scope", body:"Personal saved views only.", items:[], source_ids:[], protected:false, needs_review:false};
const snapshot: Snapshot = {id:"v1", number:1, kind:"prd", author:"assistant", summary:"First draft", parent_id:null, created_at:"2026-09-09", pins:{}, sections:[section], questions:[], assumptions:[], coverage:[], sources:[], model:"test-provider", protected_sections_kept:[]};
function fixture(): Feature {
  return {id:"feature-1", title:"Saved views", brief:"Save personal filters.", context:"", revision:3, updated_at:"2026-09-09", operations:[], comments:[], messages:[], documents:{
    prd:{head:"v1", published:null, versions:[snapshot], snapshot, stale:[], blockers:[]},
    design:{head:null,published:null,versions:[],snapshot:null,stale:[],blockers:["Generate a draft first."]},
    rfc:{head:null,published:null,versions:[],snapshot:null,stale:[],blockers:["Generate a draft first."]},
  }};
}
function mockApi(state: Feature, failure?: string) {
  const commands: Record<string, unknown>[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    let value: unknown = url.endsWith("/health") ? {contract:1} : url.endsWith("/features") ? [state] : state;
    let ok = true;
    if (init?.method === "POST") {
      commands.push(JSON.parse(init.body as string));
      if (failure) {value = {detail:failure}; ok = false;}
    }
    return {ok, json:async () => value};
  }));
  return commands;
}

beforeEach(() => {
  window.history.replaceState(null, "", "/define/studio?feature=feature-1");
  Element.prototype.scrollTo = vi.fn();
});
afterEach(() => {vi.unstubAllGlobals();});

describe("Authoring studio workflow", () => {
  it("shows the provisional document while a blocking decision remains", async () => {
    const state = fixture(); state.documents.prd.snapshot = {...snapshot, questions:[{id:"storage",question:"Where should views be stored?",why:"Affects persistence",blocking:true}]};
    state.documents.prd.blockers = ["Choose storage"];
    mockApi(state); render(<Studio />);
    expect(await screen.findByText("Personal saved views only.")).toBeInTheDocument();
    expect(screen.getByRole("button",{name:"Publish snapshot",exact:true})).toBeDisabled();
    expect(screen.getByRole("button",{name:"Review publication blockers"})).toBeEnabled();
    expect(screen.getByRole("button",{name:/Answer in chat/})).toBeEnabled();
  });

  it("sends an explicitly selected section and expected revision", async () => {
    const state=fixture(), commands=mockApi(state); render(<Studio />);
    await screen.findByText("Personal saved views only.");
    fireEvent.change(screen.getByLabelText("Revise"),{target:{value:"scope"}});
    fireEvent.change(screen.getByLabelText("Revision request"),{target:{value:"Exclude team sharing."}});
    fireEvent.click(screen.getByRole("button",{name:"Send revision request"}));
    await waitFor(() => expect(commands[0]).toMatchObject({action:"revise",kind:"prd",section_id:"scope",expected_revision:3,text:"Exclude team sharing."}));
  });

  it("retains an unsaved request when the server rejects a stale revision", async () => {
    mockApi(fixture(), "This workspace changed. Review the latest version."); render(<Studio />);
    await screen.findByText("Personal saved views only.");
    fireEvent.change(screen.getByLabelText("Revision request"),{target:{value:"Keep this request after a conflict."}});
    fireEvent.click(screen.getByRole("button",{name:"Send revision request"}));
    expect(await screen.findByRole("alert")).toHaveTextContent("This workspace changed");
    expect(screen.getByLabelText("Revision request")).toHaveValue("Keep this request after a conflict.");
  });

  it("can cancel a durable pending generation while other writes are disabled", async () => {
    const state=fixture(); state.operations=[{id:"op1",kind:"prd",status:"running",text:"Update scope",error:null,version_id:null}];
    const commands=mockApi(state); render(<Studio />);
    expect(await screen.findByRole("button",{name:"Cancel generation"})).toBeEnabled();
    expect(screen.getByRole("button",{name:"Edit Scope"})).toBeDisabled();
    fireEvent.click(screen.getByRole("button",{name:"Cancel generation"}));
    await waitFor(() => expect(commands[0]).toMatchObject({action:"cancel",expected_revision:3}));
  });

  it("reuses a request ID when retrying an unchanged request after a lost response", async () => {
    const commands = mockApi(fixture(), "The response was interrupted."); render(<Studio />);
    await screen.findByText("Personal saved views only.");
    fireEvent.change(screen.getByLabelText("Revision request"), {target:{value:"Keep sharing out of scope."}});
    fireEvent.click(screen.getByRole("button", {name:"Send revision request"}));
    await screen.findByRole("alert");
    await waitFor(() => expect(screen.getByRole("button", {name:"Send revision request"})).toBeEnabled());
    fireEvent.click(screen.getByRole("button", {name:"Send revision request"}));
    await waitFor(() => expect(commands).toHaveLength(2));
    expect(commands[0].request_id).toEqual(commands[1].request_id);
  });

  it("requires a published PRD before offering Design generation", async () => {
    mockApi(fixture()); render(<Studio />);
    await screen.findByText("Personal saved views only.");
    fireEvent.click(screen.getByRole("tab",{name:/Design spec/}));
    expect(screen.getByRole("button",{name:"Generate Design spec"})).toBeDisabled();
    expect(screen.getByText("Publish your PRD to continue.")).toBeInTheDocument();
  });

  it("keeps the direct editor open with author text after a failed save", async () => {
    const save=vi.fn().mockResolvedValue(false), close=vi.fn();
    render(<SectionEditor section={section} onClose={close} onSave={save} />);
    fireEvent.change(screen.getByLabelText("Section text · Markdown supported"),{target:{value:"My manual scope decision"}});
    fireEvent.click(screen.getByRole("button",{name:"Save new version"}));
    expect(await screen.findByRole("alert")).toHaveTextContent("Your text is still here");
    expect(screen.getByLabelText("Section text · Markdown supported")).toHaveValue("My manual scope decision");
    expect(close).not.toHaveBeenCalled();
  });
});
