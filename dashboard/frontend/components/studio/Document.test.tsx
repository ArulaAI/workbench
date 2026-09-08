import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { SectionContent } from "./Document";

describe("Generated document content", () => {
  it("renders the document without loading images from untrusted generated Markdown", () => {
    render(<SectionContent section={{id:"scope", title:"Scope", body:"Keep a readable proposal.\n\n![Untrusted external image](https://example.invalid/collect?context=private)\n\n[Explicit reference](https://example.invalid/reference)", items:[],source_ids:[],protected:false,needs_review:false}} />);
    expect(screen.getByText("Keep a readable proposal.")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByRole("link",{name:"Explicit reference"})).toHaveAttribute("href","https://example.invalid/reference");
  });
});
