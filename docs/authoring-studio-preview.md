# Try the authoring studio

The studio turns a problem statement or description into a PRD, Design spec or RFC. Start with whichever document you need, then use selected published versions for connected work. This guide covers running the independent branch, trying revisions and comments, and the experiment's boundaries.

## Open the preview

The experiment is on `codex/guided-authoring-studio`, in the `guided-authoring-studio` worktree. From that worktree's root:

```sh
.venv/bin/python scripts/authoring-studio.py start
```

Open [Authoring studio](http://localhost:3011/define/studio). The Define page also has an **Authoring studio** toolbar action. The original guided flow remains available at its existing routes.

The launcher runs this worktree's frontend on port 3011 and API on 4451. It configures matching endpoints and allowed origins, uses a separate Next.js cache, and leaves the processes running after the terminal exits. It refuses to take over an occupied port.

```sh
.venv/bin/python scripts/authoring-studio.py start --frontend-port 3012 --backend-port 4452
.venv/bin/python scripts/authoring-studio.py status
.venv/bin/python scripts/authoring-studio.py stop
```

Stopping the preview retains saved work. Logs and the local SQLite database are under `.speed/studio/`, which is ignored by Git. Run one API process per studio database.

## Start with a description

Choose **PRD**, **Design spec** or **RFC**, then describe the problem, idea or improvement. No title is required: the brief check derives one from your description and saves it for the workspace and its documents. Starting with Design or RFC does not create a PRD. Add research, constraints or decisions in the optional context field. The application uses the provider configured in `speed.toml`; this branch has been exercised with `claude-code/sonnet` through the existing authenticated Claude CLI. Generation makes real model calls.

For Design or RFC, the starting screen also offers **An existing PRD** or **An existing PRD or Design spec**. Select the workspace containing those documents, then choose the published source combination. The source picker shows the versions it will use and lets you add optional direction. The new document stays in that workspace with its source history. If the requested document or its clarification already exists, use **Open** or **Continue** to resume it. Unpublished or stale sources need publication or reconciliation first. Switching back to **A new description** keeps text already entered.

Select **Continue with brief** to check whether any product decisions need clarification. A complete brief proceeds directly to generation of the selected document. If questions are needed, the studio shows one at a time with three suggested answers and **Write my own** as the fourth option. Nothing is preselected.

**Next** saves the answer and advances. Use **Back** to review or change a saved answer before finishing. The last question has a **Generate PRD**, **Generate Design spec** or **Generate RFC** button: generation starts only after every question has a saved answer. Returning to the workspace resumes at the first unanswered question. A failed save retains your typed answer; a failed generation retains all submitted decisions.

After the document appears, use chat, section edits or comments to refine it. Later revisions can introduce new open decisions. Existing documents remain available with their original version history.

The current local preview contains **Saved views for the Define workspace**, with actual model-generated content and review history. Runtime data belongs to this checkout; a fresh clone starts empty. **Use an example** fills a brief for a fresh generation.

In that example, PRD v5 and Design v2 are published. RFC v2 is deliberately left as a draft using older sources, with a blocking review comment about its proposed data record and corruption recovery. Try **Reconcile changes**, inspect **Changes**, and address the comment to exercise the review loop. The published PRD's duplicate-name requirement already flowed into Design v2 through reconciliation.

## Edit the whole document

Use **Edit** in the document toolbar to open the PRD, Design spec or RFC in one full-page Markdown editor. The section pencil icons and edit dialog are removed. **Preview** renders the unsaved draft; **Edit** returns to the same text with undo history intact. **Save and view** saves all changes as one author version and returns to the rendered document. Opening and closing an unchanged editor does not add a version.

Required headings stay in place. Add sections with `# Heading` and subsections with `## Heading`. Structured entries appear as Markdown tables: retain existing IDs and use `new` for an added row. The server checks headings, IDs, references and RFC coverage before saving anything. Only changed sections become protected from broad AI revisions; custom sections support scoped chat revisions. Publication reviews must be repeated for the new version. Source records and published snapshots stay attached to their original versions.

Navigation to other documents is disabled during editing. Cancel asks whether to discard unsaved changes; preview does not save them. The current tab retains an unsaved draft for recovery, and failed or conflicting saves leave the editor open. **Download draft** provides a local Markdown copy. Review-card shortcuts open the same full editor at the relevant section.

## Revise and review

| Action | Result |
| --- | --- |
| Chat about the whole document | Creates a new version; directly edited sections stay protected. |
| Choose a section in the chat selector | Changes only that section. A response that tries to change another section is rejected. |
| Use Edit in the document toolbar | Edit the complete Markdown document, preview it and save all changes as one version. |
| Use a section's comment button | Anchors feedback to its section and source version. Selected text is quoted when it matches that section. |
| Address a comment | Generates a scoped revision and links it to the comment. Review the change, then resolve or dismiss the comment yourself. |
| Open Changes or Version history | Compare a version with its predecessor, inspect an older version, or restore it as a new revision. |
| Download Markdown | Exports the selected version with assumptions, open decisions and source provenance. |

After a save conflict, your editor text remains available. Download the draft if needed, close the editor, review the latest document and reopen it before saving. Network retries of an unchanged request reuse its request ID during the current page session.

## Publish and continue downstream

All documents can start from the brief and supporting context. When you add a document to an existing workspace, **Start from** makes its sources explicit:

| Document | Available starting points |
| --- | --- |
| PRD | Brief and supporting context. |
| Design spec | Brief and supporting context, or a published PRD. |
| RFC | Brief and supporting context, published PRD only, published Design only, or both published documents. |

For **PRD → RFC**, publish the PRD, select **Continue to RFC**, and use **Published PRD only (skip Design spec)**. An unfinished or stale Design draft does not block that path. To include Design, publish a current Design version and select it as a source. Generation uses the exact published versions shown; drafts are not silently included.

Each new document checks its own context and saves its own clarification answers before drafting. A standalone Design or RFC uses the same editing, version history, comments and publication reviews as a document derived from a PRD.

Before publishing, handle any **Open questions** using **Answer and update the document** or **Leave these items open for follow-up**. Answers create a new version to inspect. Leaving an item open saves a reason and follow-up plan without answering it or changing the document. When no unresolved items are detected, the page shows **No open questions found**, with no extra question confirmation. PRDs also require a **Success** review: confirm complete criteria, update missing details, or save a follow-up plan.

Once the publication checks are clear, select **I’ve reviewed this version** beside **Publish snapshot**. This is the final review of the document and its saved follow-up plans. Changes clear that selection. The toolbar leads to this review before allowing publication, and the server records it against the exact published version.

Missing targets or owners are shown with the exact text and a link to the affected metric row. For example, `unknown/TBD` in SM-1's verification column appears in the Success review. You can supply the missing detail, edit the row directly, or record a follow-up decision. Open questions review includes the document's risks/decisions section even when there are no separately generated questions.

Acknowledgements are saved for the exact version without creating extra document revisions. Any edit, AI revision, reconciliation or restore requires a fresh review. Before publishing, **Change review** lets you revise an acknowledgement. Publication preserves the review notes in its record, Markdown export and downstream generation context. An acknowledged question remains open; missing metrics do not become validated evidence.

Required content, unfinished placeholders outside these review areas, unresolved RFC coverage, blocking comments, unavailable evidence, protected sections awaiting review and upstream changes still block publication. Publication fixes a version for downstream use; it is separate from team approval and Plan readiness. Previously published snapshots remain valid; their next revision uses the new review checks.

When a newer version of a selected upstream document is published, the downstream document shows an **Upstream changed** notice. **Reconcile changes** creates a revision using the latest published sources. Old versions keep their original pins. Publishing a document that was deliberately skipped does not make the draft stale. Retries keep the original selected versions; reconciliation advances only those existing source relationships. Protected sections retain your text and require explicit review before republishing.

The RFC follows **RFC Proposal 1** and its eight-section decision core, with viable alternatives, contracts and compatibility, delivery safety, ownership and conditional engineering coverage. It uses the latest proposal's operational and AI evaluation guidance. Clarification still happens before drafting, as requested for this guided flow. Unresolved material coverage blocks publication without hiding the draft; an Open questions acknowledgement cannot override that check.

## Recover interrupted work

To remove a workspace, use the trash button on its card under **Your workspaces**. The confirmation names the workspace and explains that its documents, all versions, chat and comments will be permanently deleted. **Cancel** or Escape closes the confirmation without deleting anything. Deletion cannot be undone; download any versions you need first. Other workspaces are unaffected.

If the workspace changes while you are confirming, deletion is rejected. Close the dialog, review the updated workspace, and reopen its delete confirmation. Deleting discards pending generation results, including results that arrive after the workspace is gone.

While a request runs, the studio shows elapsed time from its saved start time, distinguishes queueing from generation, and explains waits longer than two minutes. Model responses have a three-minute limit for clarification and six minutes for document generation. The complete document appears after validation; the timer does not imply section-by-section progress. Invalid output requires an explicit retry instead of an additional hidden application-level model call.

Requests are saved before generation begins. A failed call keeps the document and submitted request; use **Retry saved request**. Server restarts mark unfinished requests interrupted. Cancelling prevents a late result from being applied; the provider may still finish its in-flight call, so cancellation does not promise immediate provider termination.

Generation receives complete current and upstream document content, with source excerpts identified separately. Oversized context fails with an explanation instead of silently omitting requirements. Large workspaces need a future retrieval/compaction strategy.

## Fresh checkout and validation

The supplied local worktree reuses the existing Python environment and has its own frontend dependency installation. For a fresh environment:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
npm --prefix dashboard/frontend ci
```

Configure and authenticate the provider in `speed.toml` before generating. Source collection reads a bounded set of tracked repository text files and records their hashes. Additional context can be pasted; file upload/import is not implemented.

```sh
.venv/bin/python -m pytest dashboard/backend/tests/test_authoring_studio.py -q
npm --prefix dashboard/frontend test -- components/studio
```

Build from `dashboard/frontend`:

```sh
SPEED_TYPESCRIPT_CONFIG=tsconfig.app.json SPEED_NEXT_DIST_DIR=.next-studio-build NEXT_PUBLIC_GRAPHQL_URL=http://127.0.0.1:4451/graphql NEXT_PUBLIC_STUDIO_URL=http://127.0.0.1:4451/studio npm run build
```

The application typecheck covers production sources. Legacy test fixtures have existing TypeScript errors under the root frontend config, so `tsconfig.app.json` excludes test files from the production build. Guided and studio tests still run through Vitest. Existing lint warnings and CodeMirror/jsdom geometry warnings are not studio failures.

The flexible-entry revision passed 58 studio backend tests, 78 guided/studio frontend tests and the production build. Checks include direct Design/RFC creation, skipping Design in any state, independent clarification answers, source selection retained through retries, clarification before generation, exact row locations, required author acknowledgements, saved notes, immutable publication records, fresh reviews after changes, and downstream propagation. Real browser/provider runs created complete standalone Design and RFC drafts with no PRD; the preview keeps them as **Direct Design demo: task due dates** and **Direct RFC demo: personal saved views**. Initial incomplete/provider responses were rejected and the saved decisions were retained for successful retries. Browser checks also confirmed the PRD-only RFC option stays available with an unpublished Design draft. Earlier review testing published a separate draft after both acknowledgements, then verified an edit required both reviews again. Desktop and mobile layouts were checked. Earlier provider testing confirmed the first PRD uses all saved clarification answers. Validation is targeted; the entire repository suite was not run.

This branch updates the inherited Next.js 15.1.6 dependency to 15.5.24, the patched maintenance release identified in the [August 2026 security advisory](https://nextjs.org/blog/august-2026-security-release). The original worktree's dependencies and manifests are unchanged.

Workspace deletion passed 66 backend tests, 85 guided/studio frontend tests and the production build. Checks cover confirmation and cancellation, stale revisions, repeated deletion, permanent version removal, transaction rollback, late worker results and unavailable workspace links. Browser testing deleted a temporary workspace with all three document types and verified that the eight existing workspaces were unchanged.

## Experiment boundaries

The [architecture and branch agenda](../specs/tech/guided-authoring-studio.md) explains the domain model and adoption work. The experiment does not migrate old sessions, write production feature packages, enforce authenticated reviewer roles, produce ADR/evaluation artifacts, or claim readiness for Plan. Structural checks cannot prove semantic correctness or evidence quality; comparison and human review remain essential.


## Record the due-date example without AI waits

Open the start screen and click **Use example**. This fills the due-date description and turns on a clearly labelled saved example. Each **Use example → Generate PRD** creates a separate workspace; existing documents are not changed. Editing the brief or supporting context, choosing Design, or clicking **Use live generation** turns this opt-in mode off before creation.

Recording sequence:

1. Click **Use example**, then **Generate PRD**. The normal brief-review loader runs for five seconds.
2. Pick the first answer to each of the three questions: keep overdue tasks at the top, allow changing/removing dates, and keep the existing completed-task view. Click **Next**, then **Generate PRD** on the last question. The draft loader runs for five seconds and shows PRD v1. Other suggestions and custom answers are saved into the requirements too.
3. Click **Edit**, add the Markdown below at the bottom, then **Save and view**. This creates v2 immediately. Open **Changes** to show the new section, then return to **Document**.

   ```markdown
   # API example

   The backend returns `highlight_color` as `#RRGGBB`. It returns `null` when no highlight applies.
   ```

4. In **Open questions**, choose **Answer and update the document**. Paste: “The design owner will review the palette and contrast before frontend rollout. The backend can ship its metadata contract first.” Click **Update document with answers**. After five seconds, v3 contains the answer. This demo action stores the text verbatim as a replacement for the linked review section; it does not use AI to interpret it. Include every decision you want to keep. Separately listed questions remain until edited explicitly.
5. In **Success**, choose **I confirm these success criteria** and save the confirmation. Then check **I’ve reviewed this version** and click **Publish snapshot**. Review evidence applies to this exact version; later edits need a fresh review.
6. Click **Continue to RFC**, keep **Published PRD only (skip Design spec)**, and generate. Brief checking and RFC loading each take five seconds. The saved RFC follows the RFC Proposal 1 section structure and includes the selected published PRD requirements and scope for review.
7. To record again, click **New workspace → Use example**. Each recording starts at v1. Demo workspaces are labelled in the list and can be deleted normally.

The fixture content is adapted from the saved “Due dates for tasks with sorting and highlighting” PRD and RFC, with a consistent three-day highlight window, an explicit hex-color contract and proposed review criteria. It is a recording scenario, not a fresh model response or proof of real-world success targets. The RFC architecture is a fixed example: copied PRD changes are available for review but are not interpreted by AI. General chat revisions, reconciliation and Design generation are unavailable in this example; use the Markdown editor for changes. Ordinary workspaces keep their existing AI flow. All example operations retain normal cancellation, retries, versioning, review and publication gates.
