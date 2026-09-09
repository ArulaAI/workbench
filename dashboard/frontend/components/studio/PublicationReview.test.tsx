import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PublicationReviewCard } from "./PublicationReview";
import type { PublicationReview } from "./types";

const review: PublicationReview = {id:"success",title:"Success",sections:[{id:"success",title:"Success"}],requires_deferral:true,
  findings:[{location:"SM-1 · Verification / outcome",anchor:"item-SM-1",excerpt:"Target is unknown/TBD; owner unknown."}],acknowledgement:null};

describe("Author publication review", () => {
  it("locates the actual metric and requires a note before acknowledging unresolved details", async () => {
    const save = vi.fn().mockResolvedValue(true);
    render(<PublicationReviewCard review={review} version="v2" busy={false} published={false} onSave={save} />);
    expect(screen.getByRole("link",{name:"SM-1 · Verification / outcome"})).toHaveAttribute("href","#item-SM-1");
    expect(screen.getByText("Target is unknown/TBD; owner unknown.")).toBeInTheDocument();
    expect(screen.getByRole("radio",{name:"I confirm these success criteria"})).toBeDisabled();
    const submit = screen.getByRole("button",{name:"Save Success acknowledgement"});
    expect(submit).toBeDisabled();
    fireEvent.click(screen.getByRole("radio",{name:/I acknowledge the unresolved/}));
    fireEvent.change(screen.getByLabelText("What remains open, and why can it wait?"),{target:{value:"   "}});
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByLabelText("What remains open, and why can it wait?"),{target:{value:"Product will agree targets after collecting the baseline."}});
    fireEvent.click(submit);
    await waitFor(() => expect(save).toHaveBeenCalledWith({action:"acknowledge_publication",review_group:"success",version_id:"v2",disposition:"deferred",text:"Product will agree targets after collecting the baseline."}));
  });
  it("allows explicit confirmation when the text has no detected unresolved details", async () => {
    const save=vi.fn().mockResolvedValue(true);
    render(<PublicationReviewCard review={{...review,requires_deferral:false,findings:[]}} version="v1" busy={false} published={false} onSave={save} />);
    screen.getAllByRole("radio").forEach(r => expect(r).not.toBeChecked());
    fireEvent.click(screen.getByRole("radio",{name:"I confirm these success criteria"}));
    fireEvent.click(screen.getByRole("button",{name:"Save Success acknowledgement"}));
    await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({disposition:"confirmed",version_id:"v1"})));
  });
  it("retains the author's note after a failed save", async () => {
    render(<PublicationReviewCard review={review} version="v2" busy={false} published={false} onSave={vi.fn().mockResolvedValue(false)} />);
    fireEvent.click(screen.getByRole("radio",{name:/I acknowledge the unresolved/}));
    fireEvent.change(screen.getByLabelText("What remains open, and why can it wait?"),{target:{value:"Keep this follow-up plan."}});
    fireEvent.click(screen.getByRole("button",{name:"Save Success acknowledgement"}));
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be saved");
    expect(screen.getByLabelText("What remains open, and why can it wait?")).toHaveValue("Keep this follow-up plan.");
  });
  it("shows unresolved acknowledgement separately from confirmation and can revoke it before publication", async () => {
    const save=vi.fn().mockResolvedValue(true);
    render(<PublicationReviewCard review={{...review,acknowledgement:{version_id:"v2",disposition:"deferred",note:"Owner to be assigned next week.",created_at:"now"}}} version="v2" busy={false} published={false} onSave={save} />);
    expect(screen.getByText("Acknowledged · still open")).toBeInTheDocument();
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
