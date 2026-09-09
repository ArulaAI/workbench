# Try the authoring studio

The studio turns a feature brief into a PRD, then uses published versions to generate Design and RFC. This guide covers running the independent branch, trying revisions and comments, and the experiment's boundaries.

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

## Try a feature

Give the feature a name and describe the desired behavior. Add research, constraints or decisions in the optional context field. The application uses the provider configured in `speed.toml`; this branch has been exercised with `claude-code/sonnet` through the existing authenticated Claude CLI. Generation makes real model calls.

Select **Continue with brief** to check whether any product decisions need clarification. A complete brief proceeds directly to PRD generation. If questions are needed, the studio shows one at a time with three suggested answers and **Write my own** as the fourth option. Nothing is preselected.

**Next** saves the answer and advances. Use **Back** to review or change a saved answer before finishing. The last question has a **Generate PRD** button: generation starts only after every question has a saved answer. Returning to the workspace resumes at the first unanswered question. A failed save retains your typed answer; a failed generation retains all submitted decisions.

After the PRD appears, use chat, section edits or comments to refine it. Later revisions can introduce new open decisions. Existing documents remain available with their original version history.

The current local preview contains **Saved views for the Define workspace**, with actual model-generated content and review history. Runtime data belongs to this checkout; a fresh clone starts empty. **Use an example** fills a brief for a fresh generation.

In that example, PRD v5 and Design v2 are published. RFC v2 is deliberately left as a draft using older sources, with a blocking review comment about its proposed data record and corruption recovery. Try **Reconcile changes**, inspect **Changes**, and address the comment to exercise the review loop. The published PRD's duplicate-name requirement already flowed into Design v2 through reconciliation.

## Revise and review

| Action | Result |
| --- | --- |
| Chat about the whole document | Creates a new version; directly edited sections stay protected. |
| Choose a section in the chat selector | Changes only that section. A response that tries to change another section is rejected. |
| Use a section's pencil button | Edit prose and structured rows. Saving creates a version and protects that section from broad AI rewrites. |
| Use a section's comment button | Anchors feedback to its section and source version. Selected text is quoted when it matches that section. |
| Address a comment | Generates a scoped revision and links it to the comment. Review the change, then resolve or dismiss the comment yourself. |
| Open Changes or Version history | Compare a version with its predecessor, inspect an older version, or restore it as a new revision. |
| Download Markdown | Exports the selected version with assumptions, open decisions and source provenance. |

After a save conflict, your editor text remains available. Copy it if needed, close the editor, review the latest section and reopen it before saving. Network retries of an unchanged request reuse its request ID during the current page session.

## Publish and continue downstream

Publish a PRD snapshot when its direction is ready to serve as an input. Design and RFC use that exact version. RFC also uses published Design when one exists; an existing Design draft must be published first.

Before publishing a PRD, review **Success** and **Open questions** using the links beside the Publish button. Design and RFC also require an Open questions review. Each review lets you confirm the content or explicitly acknowledge unresolved details. The latter requires a note explaining what remains open and why it can wait, with an owner or follow-up when known.

Missing targets or owners are shown with the exact text and a link to the affected metric row. For example, `unknown/TBD` in SM-1's verification column appears in the Success review. You can edit that row or acknowledge the pending details. Open questions review includes the document's risks/decisions section even when there are no separately generated questions.

Acknowledgements are saved for the exact version without creating extra document revisions. Any edit, AI revision, reconciliation or restore requires a fresh review. Before publishing, **Change review** lets you revise an acknowledgement. Publication preserves the review notes in its record, Markdown export and downstream generation context. An acknowledged question remains open; missing metrics do not become validated evidence.

Required content, unfinished placeholders outside these review areas, unresolved RFC coverage, blocking comments, unavailable evidence, protected sections awaiting review and upstream changes still block publication. Publication fixes a version for downstream use; it is separate from team approval and Plan readiness. Previously published snapshots remain valid; their next revision uses the new review checks.

When a newer upstream version is published, the downstream document shows an **Upstream changed** notice. **Reconcile changes** creates a revision using the latest published sources. Old versions keep their original pins. Protected sections retain your text and require explicit review before republishing.

The RFC follows the supplied eight-section proposal and assesses its conditional engineering concerns. Unresolved material coverage blocks publication without hiding the draft; an Open questions acknowledgement cannot override that check.

## Recover interrupted work

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

The publication review revision passed 44 studio backend tests, 72 guided/studio frontend tests and the production build. Checks include clarification before generation, exact row locations, required author acknowledgements, saved notes, immutable publication records, fresh reviews after changes, and downstream propagation. A browser walkthrough published a separate test draft after both acknowledgements, then verified an edit required both reviews again. Desktop and mobile layouts were checked. Earlier provider testing confirmed the first PRD uses all saved clarification answers. Validation is targeted; the entire repository suite was not run.

This branch updates the inherited Next.js 15.1.6 dependency to 15.5.24, the patched maintenance release identified in the [August 2026 security advisory](https://nextjs.org/blog/august-2026-security-release). The original worktree's dependencies and manifests are unchanged.

## Experiment boundaries

The [architecture and branch agenda](../specs/tech/guided-authoring-studio.md) explains the domain model and adoption work. The experiment does not migrate old sessions, write production feature packages, enforce authenticated reviewer roles, produce ADR/evaluation artifacts, or claim readiness for Plan. Structural checks cannot prove semantic correctness or evidence quality; comparison and human review remain essential.
