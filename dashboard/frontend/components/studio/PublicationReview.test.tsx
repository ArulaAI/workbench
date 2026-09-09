import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PublicationReviewCard } from "./PublicationReview";
import type { PublicationReview } from "./types";

const review: PublicationReview = {id:"success",title:"Success",sections:[{id:"success",title:"Success"}],requires_deferral:true,
  findings:[{location:"SM-1 · Verification / outcome",anchor:"item-SM-1",excerpt:"Target is unknown/TBD; owner unknown."}],acknowledgement:null};

describe("Author publication review", () => {
  it("accepts answers as a versioned document revision without acknowledging or publishing", async () => {
    const save = vi.fn().mockResolvedValue(true);
    const openReview: PublicationReview = {...review,id:"open_questions",title:"Open questions",sections:[{id:"decisions",title:"Open decisions and ownership"}]};
    render(<PublicationReviewCard review={openReview} version="rfc-v2" busy={false} published={false} onSave={save} />);
    fireEvent.click(screen.getByRole("radio",{name:"Answer and update the document"}));
    expect(screen.getByRole("button",{name:"Update document with answers"})).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Your answers or decisions"),{target:{value:"The platform team owns the rollout. Keep the schema question open."}});
    fireEvent.click(screen.getByRole("button",{name:"Update document with answers"}));
    await screen.findByRole("status");
    expect(save).toHaveBeenCalledOnce();
    expect(save).toHaveBeenCalledWith({action:"revise",version_id:"rfc-v2",text:expect.stringContaining("The platform team owns the rollout. Keep the schema question open.")});
    expect(screen.queryByText("Confirmed")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Your answers or decisions")).toHaveValue("The platform team owns the rollout. Keep the schema question open.");
  });

  it("keeps success answers separate from the deferral note and scopes their revision", async () => {
    const save = vi.fn().mockResolvedValue(false), edit = vi.fn();
    render(<PublicationReviewCard review={review} version="v2" busy={false} published={false} onSave={save} onEditSection={edit} />);
    fireEvent.click(screen.getByRole("button",{name:"Edit Success directly"}));
    expect(edit).toHaveBeenCalledWith("success");
    fireEvent.click(screen.getByRole("radio",{name:"Leave these items open for follow-up"}));
    fireEvent.change(screen.getByLabelText("Reason for deferring and follow-up plan"),{target:{value:"Wait for baseline collection."}});
    fireEvent.click(screen.getByRole("radio",{name:"Update the success criteria"}));
    expect(screen.getByLabelText("Success criteria and missing details")).toHaveValue("");
    fireEvent.change(screen.getByLabelText("Success criteria and missing details"),{target:{value:"SM-1 owner is the product team; target is proposed at 10%."}});
    fireEvent.click(screen.getByRole("button",{name:"Update document with answers"}));
    expect(await screen.findByRole("alert")).toHaveTextContent("answers could not be saved");
    expect(save).toHaveBeenCalledWith({action:"revise",version_id:"v2",section_id:"success",text:expect.stringContaining("SM-1 owner")});
    expect(save.mock.calls[0][0].text).not.toContain("Wait for baseline collection.");
    expect(screen.getByLabelText("Success criteria and missing details")).toHaveValue("SM-1 owner is the product team; target is proposed at 10%.");
  });

  it("locates the actual metric and requires a note before acknowledging unresolved details", async () => {
    const save = vi.fn().mockResolvedValue(true);
    render(<PublicationReviewCard review={review} version="v2" busy={false} published={false} onSave={save} />);
    expect(screen.getByRole("link",{name:"SM-1 · Verification / outcome"})).toHaveAttribute("href","#item-SM-1");
    expect(screen.getByText("Target is unknown/TBD; owner unknown.")).toBeInTheDocument();
    expect(screen.queryByRole("radio",{name:"I confirm these success criteria"})).not.toBeInTheDocument();
    expect(screen.getByRole("radio",{name:"Update the success criteria"})).toBeEnabled();
    expect(screen.getByRole("button",{name:"Save Success confirmation"})).toBeDisabled();
    fireEvent.click(screen.getByRole("radio",{name:"Leave these items open for follow-up"}));
    const submit = screen.getByRole("button",{name:"Save follow-up decision"});
    fireEvent.change(screen.getByLabelText("Reason for deferring and follow-up plan"),{target:{value:"   "}});
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Reason for deferring and follow-up plan"),{target:{value:"Product will agree targets after collecting the baseline."}});
    fireEvent.click(submit);
    await waitFor(() => expect(save).toHaveBeenCalledWith({action:"acknowledge_publication",review_group:"success",version_id:"v2",disposition:"deferred",text:"Product will agree targets after collecting the baseline."}));
  });
  it("allows explicit confirmation when the text has no detected unresolved details", async () => {
    const save=vi.fn().mockResolvedValue(true);
    render(<PublicationReviewCard review={{...review,requires_deferral:false,findings:[]}} version="v1" busy={false} published={false} onSave={save} />);
    screen.getAllByRole("radio").forEach(r => expect(r).not.toBeChecked());
    fireEvent.click(screen.getByRole("radio",{name:"I confirm these success criteria"}));
    fireEvent.click(screen.getByRole("button",{name:"Save Success confirmation"}));
    await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({disposition:"confirmed",version_id:"v1"})));
  });
  it("retains the author's note after a failed save", async () => {
    render(<PublicationReviewCard review={review} version="v2" busy={false} published={false} onSave={vi.fn().mockResolvedValue(false)} />);
    fireEvent.click(screen.getByRole("radio",{name:"Leave these items open for follow-up"}));
    fireEvent.change(screen.getByLabelText("Reason for deferring and follow-up plan"),{target:{value:"Keep this follow-up plan."}});
    fireEvent.click(screen.getByRole("button",{name:"Save follow-up decision"}));
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be saved");
    expect(screen.getByLabelText("Reason for deferring and follow-up plan")).toHaveValue("Keep this follow-up plan.");
  });
  it("shows unresolved acknowledgement separately from confirmation and can revoke it before publication", async () => {
    const save=vi.fn().mockResolvedValue(true);
    render(<PublicationReviewCard review={{...review,acknowledgement:{version_id:"v2",disposition:"deferred",note:"Owner to be assigned next week.",created_at:"now"}}} version="v2" busy={false} published={false} onSave={save} />);
    expect(screen.getByText("Deferred · still open")).toBeInTheDocument();
    expect(screen.getByText("Owner to be assigned next week.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button",{name:"Change Success review"}));
    await waitFor(() => expect(save).toHaveBeenCalledWith({action:"revoke_publication_review",review_group:"success",version_id:"v2"}));
  });
  it("keeps published review evidence read-only", () => {
    render(<PublicationReviewCard review={{...review,acknowledgement:{version_id:"v2",disposition:"deferred",note:"Accepted follow-up.",created_at:"now"}}} version="v2" busy={false} published onSave={vi.fn()} />);
    expect(screen.getByText("Accepted follow-up.")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
  });
});
