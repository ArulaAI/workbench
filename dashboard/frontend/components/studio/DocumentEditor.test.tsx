import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { DocumentEditor } from "./DocumentEditor";
import type { Snapshot } from "./types";

vi.mock("@/components/editor/SpecEditor", () => ({SpecEditor: ({content, onChange, ariaLabel}: {content:string; onChange:(value:string)=>void; ariaLabel:string}) => <textarea aria-label={ariaLabel} value={content} onChange={e => onChange(e.target.value)} />}));
const snapshot: Snapshot = {id:"v1",number:1,kind:"prd",author:"assistant",summary:"First draft",parent_id:null,created_at:"now",pins:{},sections:[],questions:[],assumptions:[],coverage:[],sources:[],model:"test",protected_sections_kept:[]};
const original = "# Summary\n\nSaved direction.\n\n# Scope\n\nPersonal tasks.\n";
beforeEach(() => {sessionStorage.clear(); vi.stubGlobal("fetch", vi.fn(async () => ({ok:true,json:async () => ({markdown:original})})));});
afterEach(() => vi.unstubAllGlobals());

describe("Whole-document Markdown editor", () => {
  it("previews unsaved edits, retains them when returning to Edit and saves once", async () => {
    const save = vi.fn().mockResolvedValue(true), close = vi.fn();
    render(<DocumentEditor featureId="f1" snapshot={snapshot} currentVersion="v1" busy={false} onSave={save} onClose={close} />);
    fireEvent.change(await screen.findByLabelText("Document Markdown"), {target:{value:original + "\n# API notes\n\nReturn **hex colors**."}});
    fireEvent.click(screen.getByRole("button", {name:"Preview",exact:true}));
    expect(screen.getByRole("heading", {name:"API notes"})).toBeInTheDocument();
    expect(screen.getByText("hex colors").tagName).toBe("STRONG");
    expect(save).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", {name:"Edit",exact:true}));
    expect((screen.getByLabelText("Document Markdown") as HTMLTextAreaElement).value).toContain("**hex colors**");
    fireEvent.click(screen.getByRole("button", {name:"Save and view"}));
    await waitFor(() => expect(close).toHaveBeenCalledOnce());
    expect(save).toHaveBeenCalledExactlyOnceWith(original + "\n# API notes\n\nReturn **hex colors**.");
    expect(sessionStorage.getItem("studio-markdown:f1:prd:v1")).toBeNull();
  });

  it("returns to view without a new version when nothing changed", async () => {
    const save = vi.fn(), close = vi.fn();
    render(<DocumentEditor featureId="f1" snapshot={snapshot} currentVersion="v1" busy={false} onSave={save} onClose={close} />);
    await screen.findByLabelText("Document Markdown");
    fireEvent.click(screen.getByRole("button", {name:"Save and view"}));
    expect(close).toHaveBeenCalledOnce(); expect(save).not.toHaveBeenCalled();
  });

  it("recovers the tab's draft, requires explicit discard and keeps it across newer-version polling", async () => {
    sessionStorage.setItem("studio-markdown:f1:prd:v1", "# Summary\n\nUnsaved words.");
    const save = vi.fn(), close = vi.fn();
    const {rerender} = render(<DocumentEditor featureId="f1" snapshot={snapshot} currentVersion="v1" busy={false} onSave={save} onClose={close} />);
    expect(await screen.findByLabelText("Document Markdown")).toHaveValue("# Summary\n\nUnsaved words.");
    rerender(<DocumentEditor featureId="f1" snapshot={snapshot} currentVersion="v2" busy={false} onSave={save} onClose={close} />);
    expect(screen.getByText(/A newer version is available/)).toBeInTheDocument();
    expect(screen.getByLabelText("Document Markdown")).toHaveValue("# Summary\n\nUnsaved words.");
    fireEvent.click(screen.getByRole("button", {name:"Cancel editing"}));
    expect(close).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", {name:"Keep editing"}));
    expect(screen.queryByRole("button", {name:"Discard changes"})).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", {name:"Cancel editing"}));
    fireEvent.click(screen.getByRole("button", {name:"Discard changes"}));
    expect(close).toHaveBeenCalledOnce(); expect(save).not.toHaveBeenCalled();
    expect(sessionStorage.getItem("studio-markdown:f1:prd:v1")).toBeNull();
  });
});
