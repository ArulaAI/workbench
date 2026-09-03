# RFC: Guided Design Drafting — PRD-Linked Vertical Slice

## Outcome

Extend the shared `workbench-draft` implementation with
`workbench draft design <feature>`. The command and conversational skill conduct
the D-Q1–D-Q8 interview from the guided-authoring contract and generate
`specs/<feature>/design.md` only from confirmed answers.

Design drafting is downstream of Product drafting. It does not create a second
feature identity, infer product scope independently, or accept a free-standing
design brief as a substitute for the feature PRD.

## Shared Implementation Boundary

PRD and Design use the same helper at
`skills/workbench-draft/scripts/draft.py`. CLI wrappers and projected skills are
adapters only. Artifact-specific question banks, section mappings, prerequisite
rules, and output paths are data selected by that helper rather than separate
implementations.

Every result reports hashes for the helper and selected question bank. Skill
projection copies both byte-for-byte, and parity tests cross entry points while
resuming one persisted checkpoint.

## Upstream PRD Contract

Before the first Design question, the helper requires:

- `specs/<feature>/prd.md`;
- `.speed/features/<feature>/authoring-prd.json` with `status: drafted`;
- the PRD path recorded by that checkpoint; and
- a content hash matching the checkpoint's generated artifact hash.

The Design checkpoint pins this input as `upstream.prd`, including its path,
SHA-256 hash, Product interview revision, question-bank version, and capture
time. Every Design result exposes the same reference.

If the PRD disappears or its content no longer matches either Product or Design
state, Design returns `upstream_changed` before changing answers or generating
an artifact. Existing Design work remains intact. Selective stale-answer repair
after an upstream change is a later slice; v1 deliberately refuses to pretend
that answers remain current.

## Interfaces

```text
workbench draft design <feature>
workbench draft design <feature> --json
workbench draft design <feature> --answer <text> --expected-revision <n> --json
workbench draft design <feature> --accept-suggestion --expected-revision <n> --json
workbench draft design <feature> --edit-suggestion --expected-revision <n> --json
workbench draft design <feature> --reject-suggestion --expected-revision <n> --json
workbench draft design <feature> --defer --expected-revision <n> --json
```

When invoked as `workbench draft design` without a feature, the helper returns
`needs_input` for `source_prd`. It offers only hash-valid generated guided PRDs,
accepts a supplied PRD reference for identity resolution, and provides
feature-name entry as a fallback when the feature cannot be derived. Arbitrary
feature directories are never offered as Design inputs.

The interaction, decision, deferral, and revision semantics match the Product
branch. Design uses its own checkpoint at
`.speed/features/<feature>/authoring-design.json` and lock.

Design questions use the same persisted one-follow-up quality contract and
two-pass deterministic self-review as Product. Findings reopen their D-Q source
answer while preserving the pinned PRD input; unresolved second-pass findings
are emitted as explicit open questions rather than independent design prose.

## Question and Evidence Contract

The versioned Design bank contains D-Q1–D-Q8 exactly as defined in
`03-guided-authoring.md`. PRD sections are routed into each question:

| Question | Primary PRD evidence |
|---|---|
| D-Q1 | Problem, Success Criteria, Scope |
| D-Q2 | User Flows, User Stories |
| D-Q3 | User Flows, Users |
| D-Q4 | User Stories, Dependencies |
| D-Q5 | User Flows, User Stories, Risks |
| D-Q6 | User Flows, Security & Controls |
| D-Q7 | Scope, Dependencies |
| D-Q8 | Users, Success Criteria, Security & Controls, Risks |

The selected PRD section excerpt is always a suggestion source. Repository
context and prior confirmed Design answers may supplement it. Raw evidence
produces an editable partial starter; a prepared response in the context
package can be accepted unchanged only when its sources are usable and no
reported gap makes it partial.

This makes Design answer size and emphasis follow actual product scope while
preserving human control over design decisions.

## Generation and Traceability

Generation runs only after D-Q1–D-Q8 are confirmed and the pinned PRD still
matches. The design header includes a relative link to `prd.md`, its pinned
hash, and Product interview revision. Each managed section includes stable
D-Q provenance. The artifact record repeats the upstream PRD reference.

Generation writes:

- `specs/<feature>/design.md`;
- `.speed/features/<feature>/draft-design.json` using the existing dashboard
  draft shape; and
- a Design row in `specs/<feature>/index.md` without removing its PRD row.

The result returns the existing feature dashboard URL at
`http://localhost:3000/define/<feature>`.

## Failure Rules

- A missing, incomplete, or hash-mismatched Product draft blocks Design before
  a Design checkpoint is created.
- A changed pinned PRD blocks resume without discarding Design answers.
- A Design answer never updates Product state or content.
- Missing or partial suggestions cannot be accepted unchanged.
- Deferred required Design questions block generation.
- Existing ceremony, context, Product draft, and unrelated specifications are
  preserved.
- Generated Design prose is repaired through its source answers, not edited as
  an independent document.

## Verification

- Design cannot start without the generated Product checkpoint and PRD.
- The first Design question exposes the PRD as a source.
- The checkpoint and generated Design both pin the exact PRD hash and revision.
- Changing the PRD blocks Design resume without changing its checkpoint.
- Eight confirmed Design answers generate a linked design artifact and
  dashboard-compatible record.
- The package index contains both Product and Design artifacts.
- CLI and projected-skill execution share implementation hashes and resume one
  Design checkpoint.
- Existing Product drafting behavior remains unchanged.
