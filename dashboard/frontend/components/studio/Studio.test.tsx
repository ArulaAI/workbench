import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
      value = state;
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
  it("replaces a temporary description title in the workspace picker after the brief check", async () => {
    const state = fixture(); state.title = "Reducing missed deadlines";
    vi.stubGlobal("fetch", vi.fn(async (url: string) => ({ok:true, json:async () =>
      url.endsWith("/health") ? {contract:1} : url.endsWith("/features") ? [{...state,title:"People keep missing time-sensitive tasks…",revision:1}] : state,
    })));
    render(<Studio />);
    fireEvent.click(await screen.findByRole("button", {name:"Reducing missed deadlines",exact:true}));
    expect(screen.getAllByRole("button", {name:"Reducing missed deadlines",exact:true})).toHaveLength(2);
    expect(screen.queryByRole("button", {name:"People keep missing time-sensitive tasks…",exact:true})).not.toBeInTheDocument();
  });

  it("returns a deleted workspace link to the list instead of leaving an endless loading screen", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => ({
      ok: !url.endsWith("/features/feature-1"), status: url.endsWith("/features/feature-1") ? 404 : 200,
      json: async () => url.endsWith("/health") ? {contract:1} : url.endsWith("/features") ? [] : {detail:"Feature not found"},
    })));
    render(<Studio />);
    await screen.findByText("This workspace is no longer available. It may have been deleted.");
    expect(screen.getByRole("heading", {name:"Your workspaces 0"})).toBeInTheDocument();
    expect(screen.queryByText("Opening your workspace…")).not.toBeInTheDocument();
    expect(window.location.search).toBe("");
  });

  it("holds publication until both reviews are saved, including when no separate questions exist", async () => {
    let state = fixture();
    state.documents.prd.snapshot = {...snapshot,sections:[section,{...section,id:"success",title:"Success",body:"Review the agreed success criteria."}]};
    state.documents.prd.publication_review = [
      {id:"success",title:"Success",sections:[{id:"success",title:"Success"}],findings:[],requires_deferral:false,acknowledgement:null},
      {id:"open_questions",title:"Open questions",sections:[],findings:[],requires_deferral:false,acknowledgement:null},
    ];
    state.documents.prd.blockers=["Review and acknowledge Success for this version.","Review and acknowledge Open questions for this version."];
    const commands: Record<string,unknown>[]=[];
    vi.stubGlobal("fetch",vi.fn(async (url:string,init?:RequestInit) => {
      if (init?.method === "POST") {
        const payload=JSON.parse(init.body as string); commands.push(payload);
        const doc=state.documents.prd;
        const reviews=doc.publication_review!.map(r => r.id === payload.review_group ? {...r,acknowledgement:{version_id:payload.version_id,disposition:payload.disposition,note:payload.text,created_at:"now"}} : r);
        state={...state,revision:state.revision+1,documents:{...state.documents,prd:{...doc,publication_review:reviews,blockers:reviews.filter(r => !r.acknowledgement).map(r => `Review and acknowledge ${r.title} for this version.`)}}};
      }
      return {ok:true,json:async () => url.endsWith("/health") ? {contract:1} : url.endsWith("/features") ? [state] : state};
    }));
    render(<Studio />);
    const success=await screen.findByRole("region",{name:"Review Success before publishing"});
    expect(screen.getByRole("button",{name:"Publish snapshot",exact:true})).toBeDisabled();
    fireEvent.click(within(success).getByRole("radio",{name:"I confirm these success criteria"}));
    fireEvent.click(within(success).getByRole("button",{name:"Save Success acknowledgement"}));
    await within(success).findByText("You confirmed this content for this version.");
    expect(screen.getByRole("button",{name:"Publish snapshot",exact:true})).toBeDisabled();
    const questions=screen.getByRole("region",{name:"Review Open questions before publishing"});
    fireEvent.click(within(questions).getByRole("radio",{name:"I confirm there are no unresolved questions"}));
    fireEvent.click(within(questions).getByRole("button",{name:"Save Open questions acknowledgement"}));
    await waitFor(() => expect(screen.getByRole("button",{name:"Publish snapshot",exact:true})).toBeEnabled());
    expect(commands.map(c => c.review_group)).toEqual(["success","open_questions"]);
    expect(commands.every(c => c.version_id === "v1")).toBe(true);
  });

  it("preserves an existing draft while a later blocking decision remains", async () => {
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

  it("allows Design generation from the brief when the PRD is unpublished", async () => {
    mockApi(fixture()); render(<Studio />);
    await screen.findByText("Personal saved views only.");
    fireEvent.click(screen.getByRole("tab",{name:/Design spec/}));
    expect(screen.getByRole("button",{name:"Generate Design spec"})).toBeEnabled();
    expect(screen.getByLabelText("Start from")).toHaveValue("brief");
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

function intakeFixture(): Feature {
  const state = fixture();
  state.documents.prd = {head:null, published:null, versions:[], snapshot:null, stale:[], blockers:["Generate a draft first."]};
  state.intake = {status:"awaiting_answers", summary:"Confirm audience and scope.", answers:{}, questions:[
    {id:"audience", question:"Who should use saved views?", why:"This determines access.", options:[
      {label:"Only me",description:"Personal access only."}, {label:"My team",description:"Share access within the team."}, {label:"Everyone",description:"Organization-wide access."}]},
    {id:"sharing", question:"What sharing belongs in this release?", why:"This determines the scope.", options:[
      {label:"No sharing",description:"Keep views personal."}, {label:"Read-only sharing",description:"Others can see a view."}, {label:"Collaborative views",description:"Others can update shared views."}]},
  ]};
  return state;
}

describe("Clarification before the first PRD", () => {
  it("offers exactly four choices and holds the document until all answers are submitted", async () => {
    let state = intakeFixture();
    const commands: Record<string, unknown>[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url:string, init?:RequestInit) => {
      if (init?.method === "POST") {
        const payload = JSON.parse(init.body as string); commands.push(payload);
        state = {...state, revision:state.revision+1, intake:{...state.intake!, answers:{...state.intake!.answers,
          [payload.question_id]:{choice:payload.choice,text:payload.text || "Only me",saved_at:"now"}}}};
        if (Object.keys(state.intake!.answers).length === 2) {
          state.intake!.status = "ready";
          state.operations = [{id:"generate",action:"generate",kind:"prd",status:"queued",text:"Generate using all answers",error:null,version_id:null}];
        }
      }
      return {ok:true,json:async () => url.endsWith("/health") ? {contract:1} : url.endsWith("/features") ? [state] : state};
    }));
    render(<Studio />);
    await screen.findByRole("heading",{name:"Who should use saved views?"});
    expect(screen.getAllByRole("radio")).toHaveLength(4);
    screen.getAllByRole("radio").forEach(r => expect(r).not.toBeChecked());
    expect(screen.getByRole("button",{name:"Next",exact:true})).toBeDisabled();
    expect(screen.queryByText("Personal saved views only.")).not.toBeInTheDocument();
    expect(screen.queryByRole("button",{name:"Publish snapshot"})).not.toBeInTheDocument();
    expect(screen.getByRole("tab",{name:/Design spec/})).toBeDisabled();
    fireEvent.click(screen.getByRole("radio",{name:/Only me/}));
    fireEvent.click(screen.getByRole("button",{name:"Next",exact:true}));
    await screen.findByRole("heading",{name:"What sharing belongs in this release?"});
    expect(commands[0]).toMatchObject({action:"answer_clarification",kind:"prd",question_id:"audience",choice:"option-1",expected_revision:3});
    expect(state.documents.prd.head).toBeNull();
    fireEvent.click(screen.getByRole("button",{name:"Back",exact:true}));
    expect(screen.getByRole("radio",{name:/Only me/})).toBeChecked();
    fireEvent.click(screen.getByRole("button",{name:"Next",exact:true}));
    await screen.findByRole("heading",{name:"What sharing belongs in this release?"});
    fireEvent.click(screen.getByRole("radio",{name:/Write my own/}));
    expect(screen.getByRole("button",{name:"Generate PRD",exact:true})).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Your answer"),{target:{value:"Only invite-only read access in the first release."}});
    fireEvent.click(screen.getByRole("button",{name:"Generate PRD",exact:true}));
    await screen.findByRole("heading",{name:"Creating your first PRD"});
    expect(commands.at(-1)).toMatchObject({action:"answer_clarification",question_id:"sharing",choice:"custom",text:"Only invite-only read access in the first release."});
    expect(screen.queryByText("Personal saved views only.")).not.toBeInTheDocument();
  });

  it("resumes at the first unanswered question after returning to a workspace", async () => {
    const state = intakeFixture();
    state.intake!.answers.audience = {choice:"option-2",text:"My team",saved_at:"now"};
    mockApi(state); render(<Studio />);
    await screen.findByRole("heading",{name:"What sharing belongs in this release?"});
    expect(screen.getByText("Question 2 of 2")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button",{name:"Back",exact:true}));
    expect(screen.getByRole("radio",{name:/My team/})).toBeChecked();
  });

  it("retains a custom answer if saving fails", async () => {
    mockApi(intakeFixture(), "Your answer could not be saved. Try again."); render(<Studio />);
    await screen.findByRole("heading",{name:"Who should use saved views?"});
    fireEvent.click(screen.getByRole("radio",{name:/Write my own/}));
    fireEvent.change(screen.getByLabelText("Your answer"),{target:{value:"Only invited project owners."}});
    fireEvent.click(screen.getByRole("button",{name:"Next",exact:true}));
    await screen.findByRole("alert");
    expect(screen.getByLabelText("Your answer")).toHaveValue("Only invited project owners.");
    expect(screen.getByText("Question 1 of 2")).toBeInTheDocument();
  });

  it("shows a brief check before any drafting controls", async () => {
    const state = intakeFixture();
    state.intake = {...state.intake!, status:"checking",questions:[]};
    state.operations = [{id:"check",kind:"prd",action:"clarify",status:"running",text:state.brief,error:null,version_id:null}];
    mockApi(state); render(<Studio />);
    await screen.findByRole("heading",{name:"Reviewing your brief"});
    expect(screen.getByRole("button",{name:"Cancel brief review"})).toBeEnabled();
    expect(screen.queryByRole("button",{name:"Generate PRD",exact:true})).not.toBeInTheDocument();
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
  });
});

describe("Flexible document entry points", () => {
  it.each([['prd','PRD'], ['design','Design spec'], ['rfc','RFC']] as const)("starts %s from a description without requesting a title", async (kind, label) => {
    window.history.replaceState(null, '', '/define/studio');
    const state=fixture(); state.initial_kind=kind;
    state.documents.prd={head:null,published:null,versions:[],snapshot:null,stale:[],blockers:[]};
    state.intakes={[kind]:{status:'checking',summary:'',questions:[],answers:{}}};
    state.operations=[{id:'initial-check',kind,action:'clarify',status:'queued',text:'Check context',error:null,version_id:null}];
    const commands=mockApi(state); render(<Studio />);
    await screen.findByRole('button',{name:'Continue with brief'});
    expect(screen.queryByRole('textbox', {name:/name|title/i})).not.toBeInTheDocument();
    expect(screen.getByRole('button',{name:'Continue with brief'})).toBeDisabled();
    fireEvent.click(screen.getByRole('radio',{name:new RegExp(`^${label}`)}));
    fireEvent.change(screen.getByLabelText('Describe what you want to solve'),{target:{value:'Save and reopen personal filter views.'}});
    await waitFor(() => expect(screen.getByRole('button',{name:'Continue with brief'})).toBeEnabled());
    fireEvent.click(screen.getByRole('button',{name:'Continue with brief'}));
    await screen.findByRole('region',{name:`${label} clarification`});
    expect(commands[0]).toMatchObject({kind,brief:'Save and reopen personal filter views.'});
    expect(commands[0]).not.toHaveProperty('title');
    expect(screen.getByRole('tab',{name:new RegExp(label)})).toHaveAttribute('aria-selected','true');
    expect(window.location.search).toContain(`document=${kind}`);
  });

  it('offers PRD-only RFC generation even with an unpublished Design draft', async () => {
    const state=fixture(); state.documents.prd.published='v1';
    state.documents.design={...state.documents.prd,published:null,snapshot:{...snapshot,kind:'design'}};
    const commands=mockApi(state); render(<Studio />);
    await screen.findByText('Personal saved views only.');
    fireEvent.click(screen.getByRole('tab',{name:/RFC/}));
    expect(screen.getByLabelText('Start from')).toHaveValue('prd');
    expect(screen.getByRole('option',{name:'Published PRD only (skip Design spec)'})).toBeEnabled();
    expect(screen.getByRole('option',{name:/Published PRD and Design spec/})).toBeDisabled();
    fireEvent.click(screen.getByRole('button',{name:'Generate RFC',exact:true}));
    await waitFor(() => expect(commands[0]).toMatchObject({action:'generate',kind:'rfc',source_mode:'prd'}));
  });

  it('allows an explicit brief-only RFC even when a published PRD exists', async () => {
    const state=fixture(); state.documents.prd.published='v1';
    const commands=mockApi(state); render(<Studio />);
    await screen.findByText('Personal saved views only.');
    fireEvent.click(screen.getByRole('tab',{name:/RFC/}));
    fireEvent.change(screen.getByLabelText('Start from'),{target:{value:'brief'}});
    fireEvent.click(screen.getByRole('button',{name:'Generate RFC',exact:true}));
    await waitFor(() => expect(commands[0]).toMatchObject({action:'generate',kind:'rfc',source_mode:'brief'}));
  });

  it('saves an RFC clarification answer to the RFC intake', async () => {
    window.history.replaceState(null,'','/define/studio?feature=feature-1&document=rfc');
    const state=intakeFixture();
    state.intakes={rfc:{...state.intake!,questions:[state.intake!.questions[0]]}};delete state.intake;
    state.initial_kind='rfc';
    const commands=mockApi(state);render(<Studio />);
    await screen.findByRole('region',{name:'RFC clarification'});
    fireEvent.click(screen.getByRole('radio',{name:/Only me/}));
    fireEvent.click(screen.getByRole('button',{name:'Generate RFC',exact:true}));
    await waitFor(() => expect(commands[0]).toMatchObject({action:'answer_clarification',kind:'rfc',question_id:'audience',choice:'option-1'}));
  });
});

it('keeps stale published Design unavailable even when its latest draft is reconciled', async () => {
  const state=fixture(); state.documents.prd.published='v1';
  state.documents.design={...state.documents.prd,head:'design-v2',published:'design-v1',stale:[],published_stale:['prd'],snapshot:{...snapshot,id:'design-v2',kind:'design'}};
  mockApi(state); render(<Studio />);
  await screen.findByText('Personal saved views only.');
  fireEvent.click(screen.getByRole('tab',{name:/RFC/}));
  expect(screen.getByRole('option',{name:/Published PRD and Design spec/})).toBeDisabled();
  expect(screen.getByRole('option',{name:/Published Design spec only/})).toBeDisabled();
  expect(screen.getByRole('button',{name:'Generate RFC',exact:true})).toBeEnabled();
});
