# RFC: Define Feature — Findings and Defect Intake

> Product: [Define Feature: Evidence-to-Defect Intake](../product/speed-define-feature-defects.md).
> Design: [Findings inbox and defect report](../design/speed-define-feature-defects.md).
> Existing workflow: [Defect Pipeline](speed-defects.md).
> Status: implemented for review on `feat/speed-define-feature-defects`, from baseline `e95e62e`. **V1 consumes Diagnose and code review. Eval becomes an additional input in V2.**

## Basic Example

An engineer sees a code-review finding about duplicate charges, completes its defect draft, and files it. Define writes the report and initializes the existing defect state. The engineer then runs the existing defect command.

```sh
speed define feature payments --no-open
speed define defects --feature payments --feature refunds --json
speed defect specs/defects/refund-retry-double-charge.md
```

```text
Existing Diagnose / code-review output
  → /define/payments/findings
  → user selects Create defect
  → editable preview; no files written
  → user completes reproduction steps and confirms severity
  → specs/defects/refund-retry-double-charge.md + existing defect state
  → /define/defects?feature=payments
  → existing speed defect pipeline
```

V1 does not claim an executed failure merely because a reviewer suspects one. A review summary remains supporting context; only an explicitly labeled `observed` or `actual` field can populate Observed Behavior. Missing facts remain visibly incomplete. Eval will supply execution evidence in V2 through the input boundary below.

## Scope and terminology

**This is a defect intake feature, not a new review workflow.**

| Term | Meaning in this RFC | Existing code |
|---|---|---|
| Code review | Implementation feedback produced by `speed review` | `lib/cmd/review.sh` |
| Spec ratification | Approval of a committed specification | `/define/[feature]/review`; unchanged |
| Finding decision | A person's action on evidence: fix, file, verify, defer, dismiss, or link a duplicate | New `findings.json`; never `review.json` |
| Defect review | Reviewing a proposed defect fix inside the existing pipeline | `lib/defect_review.sh`; unchanged |
| Outcome approval | Permission to ship a feature with known failures | Separate product scope; no new approval operation here |

**NEW** means a new file or symbol. **UPDATE** means an existing implementation changes. **DELETE** means an existing body or proposal is removed. **REUSE** means call or render existing code without modifying it. **V2** means a future extension excluded from V1. The file-impact table is measured from the implementation branch; code blocks below describe its review contracts. The reviewer should still challenge the tradeoffs and acceptance cases before approving the branch.

### DELETE — unnecessary work from the previous proposal

| Removed proposal | Why it is unnecessary for defect intake |
|---|---|
| Move `SpeedPaths` and re-export it | `dashboard/backend/paths.py` already has a dependency-light implementation; both adapters can import it unchanged. |
| Extract ceremony claim locking into a general library | Defect intake can own its short filesystem lock without changing ceremony claims. |
| Create general security-pattern/redaction modules | Keep raw logs out of reports; extract only the existing pattern-list helper needed to scan a draft (explicit exception below). |
| Refactor Learn's code-review parser and weighting | This feature persists decisions. Learning from them is a separate consumer change. |
| Write findings into planned outcome `review.json` | It conflates defect decisions with feature approval and assumes an unimplemented storage contract. |
| Add Eval handoff ingestion and fixtures in V1 | Eval is a V2 input. Reserve its adapter contract without inventing a current producer or file layout. |
| Change outcome judging, reviewer prompts, Diagnose rule engine, global colors, global CSS, or shared loading skeletons | None is required to read evidence, file a defect, or report existing defects. |

These deletions refer to the earlier proposal. The implementation deletes superseded function bodies inside existing files; it deletes no whole source file.

### Delivery boundary

V1 includes findings from implemented sources, immutable evidence history, manual grouping/splitting, all six finding decisions, rework linkage, no-write drafts, filing/recovery, later evidence attachment, manager reporting, and CLI inspection/export. Scope is driven by the linked PRD, not by opportunities to clean up the repository.

Eval-derived execution confidence, run/build provenance, and scenario correlation arrive in V2. V1 neither probes an imagined Eval directory nor labels absent Eval as a failure. `criteria-verify.json` retains its existing meaning and is not an Eval substitute.

The product/design documents describe the wider destination. Their Eval examples are V2 acceptance cases. Their outcome approval and Learn integration requirements are **not fulfilled by this RFC**: decision history remains available, but no ship-with-known-defect authorization or learning extraction is implemented. Accept/defer records intent only; it cannot approve a release. These differences are explicit implementation boundaries, not hidden dependencies or claims of complete PRD delivery.

## Verified code and reuse

The table includes both modified code and dependencies used unchanged. Being listed here does **not** mean a file changes. In particular, `dashboard/backend/paths.py`, `dashboard/backend/resolvers/ceremony_types.py`, and `lib/cmd/ceremony.sh` have **no edits**.

### Why changes reach outside defect modules

| Filename | Exact reason for the implemented edit | Is it required just to file a defect? |
|---|---|---|
| `lib/cmd/diagnose.sh` | Preserve each task's output before the next invocation overwrites the feature's single `risk-surface.yaml`. This supports the PRD's complete findings/history requirement. | **No.** Intake could read and snapshot only the surviving file, but signals from earlier tasks/runs could already be lost. |
| `lib/cmd/review.sh` | Preserve prior output before a rerun replaces the same task's review file; capture the commit actually inspected. This supports evidence provenance and before/after rework history. | **No.** Reading current output suffices for a draft; it cannot recover overwritten attempts or establish missing historical commit identity. |
| `lib/tasks.sh` and `lib/cmd/run.sh` | The queued **Fix in this feature** action uses the existing transition and adds a request marker so crash recovery cannot enqueue the same work twice. | **No. This is a design choice for rework delivery, not an intake prerequisite.** A link-only action could leave both files unchanged. Structured code review already requeues tasks when it requests changes. |
| `dashboard/backend/paths.py` | Resolve the existing single-player/multiplayer directories. | **No edit.** Import and call the existing class. |
| `dashboard/backend/resolvers/ceremony_types.py`; `lib/cmd/ceremony.sh` | Use `get_current_actor()` from the former for attribution. No ceremony command or approval behavior participates in filing. | **No edit to either file.** |
| `speed` | Register `speed define`; preserve repeated feature filters before global parsing consumes them; avoid the heartbeat write for read-only Define commands; refresh the defect root after multiplayer detection. | **Required for the specified CLI entry point and MP path correction.** The parser/heartbeat changes are specific to Define; other command parsing is unchanged. |

The source-writer and task changes serve history/rework requirements. They are not dependencies of merely creating a Markdown defect report. The alternatives above explain what would be lost or changed if that scope is reduced.

### Existing functions and reuse

| Filename | Existing implementation | What was verified | Implemented change |
|---|---|---|---|
| [dashboard/backend/resolvers/define.py](../../dashboard/backend/resolvers/define.py) | `_build_defects()` (line 519) | Unions state and canonical reports, deduplicates names, clamps unknown severity to P3, labels spec-only records `open`. | **UPDATE:** move this defect discovery/parsing into one shared defect reader; preserve the Define adapter. |
| [dashboard/backend/resolvers/context.py](../../dashboard/backend/resolvers/context.py) | `read_defects()` (line 708) | Independently reads defects with file/tag relevance rules. | **UPDATE:** reuse defect metadata, preserve its contextual relevance policy. Exact manager filtering remains separate. |
| [lib/defects.sh](../../lib/defects.sh) | `defect_validate_report`, `parse_defect_report`, `defect_resolve_specs`, `defect_escalate_to_prd` | Different parsers recognize different subsets of the two existing templates. | **UPDATE/DELETE:** replace only field extraction with one parser, keep shell entry points and return conventions. |
| [lib/defects.sh](../../lib/defects.sh) | `defect_init` and `create_defect_state` | Existing fresh-pipeline state builders already establish the legacy contract. | **REUSE unchanged:** intake writes a shape-compatible filed state through `initial_defect_state`; changing these shell builders is unnecessary. |
| [lib/cmd/defect.sh](../../lib/cmd/defect.sh) | `cmd_defect()` (line 4) | Existing-state switch has no `filed` branch and can print “resolved” without doing work. | **UPDATE:** let validated `filed` state enter the same triage path as a fresh report. |
| [lib/defect_triage.sh](../../lib/defect_triage.sh) | `triage_defect()` (line 293) | Always initializes a new directory before triage; moderate triage intentionally stops for human review. | **UPDATE:** reuse complete filed state; preserve complexity routing and the human stop. |
| [lib/cmd/diagnose.sh](../../lib/cmd/diagnose.sh) | `cmd_diagnose()` output writer (line 115) | Overwrites `FEATURE_DIR/risk-surface.yaml`; class signals contain `observed` and `where`. | **UPDATE:** retain an immutable normalized attempt before replacing that compatibility output. |
| [lib/cmd/review.sh](../../lib/cmd/review.sh) | `cmd_review()` / `_cmd_review_task()` | Structured mode writes `logs/review-<id>.json`; pre-contract clean-context mode could write `reviews/task-<id>.review` as plain text. | **UPDATE:** archive both as distinct producers. Current clean-review output must pass the versioned contract; arbitrary prose is readable only as legacy evidence and is never interpreted as a structured verdict. |
| [lib/tasks.sh](../../lib/tasks.sh) | `task_request_changes(id, feedback)` | Atomically sets `pending`, `review_feedback`, and `review_verdict=request_changes`. Structured review already calls it. | **UPDATE:** add only the optional request marker for the finding rework queue. **REUSE:** the existing pending/feedback transition; no second task transition implementation. |
| [dashboard/backend/paths.py](../../dashboard/backend/paths.py); [dashboard/backend/resolvers/ceremony_types.py](../../dashboard/backend/resolvers/ceremony_types.py) | `SpeedPaths`; `get_current_actor()` | Existing SP/MP path resolution and server-derived `(name, email)`. | **REUSE:** unchanged. Library functions receive paths/actor; client inputs cannot impersonate an actor. |
| [dashboard/frontend/app/editor/page.tsx](../../dashboard/frontend/app/editor/page.tsx); [dashboard/backend/spec_registry.py](../../dashboard/backend/spec_registry.py) | `openSpec(path)`; `update_spec(conn, path, project_root)` | Editor already opens defect tabs; filing can index a newly created canonical report. | **REUSE:** add URL entry handling; call the existing registry function after filing. |
| [speed](../../speed) | Startup and global argument loop | Defect root is chosen before MP detection; repeated `--feature` values are consumed as a single global feature; MP heartbeat writes on dispatch. | **UPDATE:** narrowly fix root refresh and route Define arguments before global parsing/heartbeat. |

The source of truth stays in files. SQLite remains the existing editor index. No new database, task engine, defect lifecycle, or review command is introduced.

## File Impact and Lines of Code

Every V1 implementation file is listed below. Counts come from `git diff --numstat` for tracked files and physical line counts for new files on `feat/speed-define-feature-defects`. The three specification documents, generated files, dependencies, and unrelated pre-existing untracked job-description files are excluded.

**Measured V1 diff: 39 files (19 NEW, 20 UPDATE), +4,250 / −366 lines; net +3,884; 4,616 changed lines. No whole-file deletions.** Production/config is +3,489/−366 across 32 files. Tests are +761/−0 across 7 files.

| Area | Files | Add | Remove | Net |
|---|---:|---:|---:|---:|
| Shared defect core and configuration | 9 | +2,362 | −26 | +2,336 |
| Existing CLI and defect workflow | 9 | +257 | −132 | +125 |
| Dashboard backend | 6 | +310 | −195 | +115 |
| Dashboard frontend | 8 | +560 | −13 | +547 |
| Tests | 7 | +761 | −0 | +761 |
| **Total** | **39** | **+4,250** | **−366** | **+3,884** |

### Shared defect core and configuration

| Change | Filename | Add | Remove | Net | Implemented reason |
|---|---|---:|---:|---:|---|
| NEW | `lib/defect_reports.py` | +550 | −0 | +550 | One report parser, initial state, inventory, filters, export, readiness, and existing secret-pattern adapter. |
| NEW | `lib/defect_findings.py` | +853 | −0 | +853 | Immutable evidence archives, source normalization, grouping, decisions, consistent reads, revisions, and rework records. |
| NEW | `lib/defect_intake.py` | +588 | −0 | +588 | Deterministic preview, validation, branch staleness, locking, atomic receipt staging, filing recovery, regressions, and evidence attachment. |
| NEW | `lib/defect_report_cli.py` | +106 | −0 | +106 | Stable shell adapter for the shared parser and intake readiness. |
| NEW | `lib/define_cli.py` | +114 | −0 | +114 | Read-only feature inbox and defect-report CLI renderer/exporter. |
| NEW | `lib/evidence_cli.py` | +69 | −0 | +69 | Shell-to-Python publication adapter for Diagnose and both existing Review outputs. |
| NEW | `lib/review_evidence.py` | +120 | −0 | +120 | Versioned clean-review parser and validator, with an explicit compatibility path for pre-contract artifacts. |
| NEW | `lib/rework_cli.py` | +55 | −0 | +55 | Lock-safe queue read and acknowledgement used by the existing run command. |
| UPDATE | `lib/grounding.sh` | +26 | −26 | 0 | Extract the existing secret regex pairs without changing scanner behavior. |
| UPDATE | `requirements.txt` | +1 | −0 | +1 | Declare PyYAML for Diagnose YAML and report frontmatter. |

### Existing CLI and defect workflow

| Change | Filename | Add | Remove | Net | Implemented reason |
|---|---|---:|---:|---:|---|
| UPDATE | `speed` | +11 | −0 | +11 | Route Define before global flag consumption and heartbeat; refresh the defect root after MP detection. |
| NEW | `lib/cmd/define.sh` | +31 | −0 | +31 | Thin read-only wrapper over `lib/define_cli.py`; opens only an already-running UI. |
| UPDATE | `lib/defects.sh` | +31 | −75 | −44 | Replace duplicate report parsing with the shared adapter and add MP/readiness helpers. |
| UPDATE | `lib/cmd/defect.sh` | +37 | −22 | +15 | Validate paths/intake, resume `filed`, and reject unknown state instead of reporting success. |
| UPDATE | `lib/defect_triage.sh` | +33 | −27 | +6 | Reuse a valid filed intake and resolve all related feature specs through the shared parser. |
| UPDATE | `lib/cmd/diagnose.sh` | +24 | −2 | +22 | Publish attempt, commit, and diff identity before atomically replacing `risk-surface.yaml`. |
| UPDATE | `lib/cmd/review.sh` | +38 | −4 | +34 | Publish structured and clean Review attempts before replacing compatibility outputs. |
| UPDATE | `lib/tasks.sh` | +9 | −2 | +7 | Add an optional idempotent finding request marker to the existing request-changes transition. |
| UPDATE | `lib/cmd/run.sh` | +43 | −0 | +43 | Apply queued finding rework after acquiring the existing run lock. |

### Dashboard backend

| Change | Filename | Add | Remove | Net | Implemented reason |
|---|---|---:|---:|---:|---|
| UPDATE | `dashboard/backend/resolvers/define.py` | +14 | −107 | −93 | Delete its duplicate defect parser and project the shared inventory into the existing Define type. |
| UPDATE | `dashboard/backend/resolvers/context.py` | +19 | −87 | −68 | Delete duplicate discovery while retaining context-specific file/feature/tag relevance. |
| UPDATE | `dashboard/backend/resolvers/define_types.py` | +9 | −1 | +8 | Expose canonical, related-feature, source-finding, readiness, and warning metadata. |
| NEW | `dashboard/backend/resolvers/feature_defect_types.py` | +71 | −0 | +71 | Typed mutation inputs only; domain data remains in the shared core. |
| NEW | `dashboard/backend/resolvers/feature_defects.py` | +126 | −0 | +126 | Thin query/mutation adapters, server actor, and existing spec-registry update after filing. |
| UPDATE | `dashboard/backend/schema.py` | +71 | −0 | +71 | Register four JSON queries and four typed-input mutations. |

### Dashboard frontend

| Change | Filename | Add | Remove | Net | Implemented reason |
|---|---|---:|---:|---:|---|
| NEW | `dashboard/frontend/app/define/[feature]/findings/page.tsx` | +243 | −0 | +243 | Inbox, filters, source disclosure, six decisions, grouping, evidence update, return navigation, and recoverable deterministic draft dialog. |
| NEW | `dashboard/frontend/app/define/defects/page.tsx` | +87 | −0 | +87 | URL-backed multi-filters, server totals/grouping, provenance links, warnings, and revision-checked exports. |
| NEW | `dashboard/frontend/lib/graphql/queries/feature-defects.ts` | +135 | −0 | +135 | New operations and transport interfaces. |
| UPDATE | `dashboard/frontend/app/define/page.tsx` | +6 | −0 | +6 | Add the defect-report entry point. |
| UPDATE | `dashboard/frontend/app/define/[feature]/page.tsx` | +12 | −2 | +10 | Add the findings entry point to every valid feature state. |
| UPDATE | `dashboard/frontend/app/editor/page.tsx` | +37 | −9 | +28 | Validate `spec`/legacy `path`, make the canonical target win hydration, and preserve a safe return URL. |
| UPDATE | `dashboard/frontend/components/define/defect-row.tsx` | +22 | −2 | +20 | Reuse the row for the report table, canonical/source links, affected features, and warnings. |
| UPDATE | `dashboard/frontend/lib/graphql/queries/define.ts` | +18 | −0 | +18 | Additive metadata fields for the reused row and editor navigator. |

### Tests

| Change | Filename | Add | Remove | Net | Covered behavior |
|---|---|---:|---:|---:|---|
| NEW | `tests/test_defect_reports.py` | +99 | −0 | +99 | Both report shapes, bold/empty metadata, union inventory, filters, lifecycle, Unassigned, and symlink containment. |
| NEW | `tests/test_defect_findings.py` | +175 | −0 | +175 | Source meaning, history, rework resolution, grouping, redaction, legacy freezing, and containment. |
| NEW | `tests/test_review_evidence.py` | +98 | −0 | +98 | Strict current schema, provider-fence tolerance, unsafe locations, legacy compatibility, and preservation on rejected reruns. |
| NEW | `tests/test_defect_intake.py` | +255 | −0 | +255 | SP/MP preview, filing, replay, staging/commit faults, branch staleness, evidence append, and resolved regression. |
| NEW | `tests/test_define_cli.py` | +73 | −0 | +73 | Real `speed define` SP/MP reads, repeated filters, and no-write inspection. |
| NEW | `tests/test_rework_cli.py` | +40 | −0 | +40 | Queue read, idempotent acknowledgement, and revision update. |
| NEW | `dashboard/backend/tests/test_feature_defects.py` | +91 | −0 | +91 | GraphQL read/file paths, stale export rejection, provenance projection, and incremental editor indexing. |
| UPDATE | `tests/test_tasks.sh` | +28 | −0 | +28 | Rework-marker replay and preservation of existing review feedback. |

**DELETE within existing files:** the duplicate parsers in `dashboard/backend/resolvers/define.py`, `dashboard/backend/resolvers/context.py`, and `lib/defects.sh`. Public adapters remain. **UNCHANGED:** `dashboard/backend/paths.py`, `dashboard/backend/resolvers/ceremony_types.py`, `lib/cmd/ceremony.sh`, `lib/defect_fix.sh`, `templates/defect-report.md`, `templates/defect.md`, global CSS, and outcome-review storage.

## Data Model

Read the model as three steps: **evidence says what a tool reported; a decision says what a person chose; a defect is the existing report plus pipeline state.** Findings are the grouped view joining evidence and decisions, not a second defect lifecycle.

### NEW — source evidence and findings (`lib/defect_findings.py`)

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Source = Literal["diagnose", "code_review", "eval"]  # eval reserved for V2
Action = Literal[
    "fix_in_feature", "create_defect", "needs_verification",
    "accept_defer", "false_positive", "duplicate",
]

@dataclass(frozen=True)
class Evidence:
    id: str                       # hash of producer/task/item_key/content_hash
    source: Source
    producer: str                 # diagnose, structured_review, clean_review
    task_id: str | None
    item_key: str                 # source-local issue identity, defined below
    artifact_path: str            # project-relative archive or mutable legacy path
    artifact_hash: str            # SHA-256 of bytes at artifact_path
    content_hash: str             # original producer bytes; stable across archival
    summary: str
    observed: str | None
    expected: str | None
    reproduction: str | None
    files: tuple[str, ...]
    requirement_ids: tuple[str, ...]
    issue_key: str | None         # explicit shared issue identity; never inferred
    commit: str | None            # inspected commit; not a claim about a build
    verdict: str | None           # preserved source verdict, if structured
    severity: str | None          # source label, not confirmed defect priority
    confidence: Literal["unjudged", "interpreted", "unknown"]  # V1 source meaning
    attempt_id: str | None        # unknown for legacy files
    diff_hash: str | None         # hash of the diff supplied to the source

@dataclass(frozen=True)
class Finding:
    id: str                       # stable group ID, not an evidence revision
    revision: str                 # digest of current members + relevant inputs
    evidence: tuple[Evidence, ...]
    decision_id: str | None       # latest applicable decision, if any
    stale: bool                   # decision refers to older evidence
    resolution: Literal[
        "unresolved", "rework_queued", "rework_applied", "rework_blocked",
        "resolved_by_rework", "filed", "needs_verification",
        "accepted_deferred", "false_positive", "duplicate",
    ]
    recommended_action: Literal[
        "investigate", "fix_in_feature", "fix_scope",
        "needs_verification", "consider_defect", "accept",
    ]
    allowed_actions: tuple[Action, ...]
    linked_defect_slug: str | None

@dataclass(frozen=True)
class Decision:
    id: str                       # request UUID; retries reuse it
    finding_id: str
    evidence_ids: tuple[str, ...] # exact evidence decided upon
    event_kind: Literal["disposition", "evidence_attachment"]
    action: Action | None         # null only for an evidence attachment
    rationale: str
    actor_name: str               # server supplied
    actor_email: str              # server supplied
    at: str                      # UTC ISO timestamp
    task_id: str | None
    defect_slug: str | None
```

**Identity:** structured-review `item_key` hashes the array name and normalized item content, excluding line number; repeated identical items receive an occurrence suffix. Diagnose uses class ID plus normalized signal content. Clean prose is one inspectable item per task/output hash. These are conservative identities: changes in wording can create a new candidate. Do not claim perfect equivalence from legacy data.

Across attempts, exact `(producer, task_id, item_key)` matches retain finding identity. Across sources, auto-group only by an explicit shared `issue_key`; matching task IDs, filenames, or requirement IDs alone is insufficient. Otherwise the user can merge/split findings. Persist the resulting membership mapping; do not ask an LLM to guess equivalence.

### NEW — one feature decision file

Location: `SpeedPaths.feature_shared(feature) / "findings.json"`. Missing file means an empty history; reads never create it. Corrupt/unknown versions produce a warning and block writes, rather than replacing history with an empty record.

```json
{
  "schema_version": 1,
  "revision": 3,
  "groups": {
    "finding-retry": ["structured_review:4:issues:issue-hash"]
  },
  "decisions": [{
    "id": "c53012e6-631b-424b-9eb8-08bd5a3039ba",
    "finding_id": "finding-retry",
    "evidence_ids": ["evidence-content-hash"],
    "event_kind": "disposition",
    "action": "create_defect",
    "rationale": "Track this separately for the next payments release.",
    "actor_name": "Alex",
    "actor_email": "alex@example.test",
    "at": "2026-09-21T18:00:00Z",
    "task_id": "4",
    "defect_slug": "refund-retry-double-charge"
  }],
  "group_history": [],
  "rework": {}
}
```

Hash placeholders in examples stand for full SHA-256 hex strings. `groups` maps finding IDs to source identity strings, not changing evidence IDs. Decisions retain exact evidence IDs. Manual merge/split appends a grouping-history entry (request ID, previous/new memberships, actor, time, rationale); it never rewrites prior decisions. A split affecting an already filed finding requires an explicit choice of which resulting finding retains the defect link.

`rework` maps decision ID to `{task_id, status, error}`; status is `queued`, `applied`, or `blocked`. It is delivery bookkeeping, separate from the append-only decision. Feature revision increments on every mutation, including rework acknowledgments. New contradictory evidence makes a prior dismissal/defer decision stale; vanished evidence alone does not prove a fix.

### UPDATE — existing defect report and state

There is no new defect model to synchronize. The Markdown report describes the bug; `state.json` owns pipeline status. The state additions below are provenance and reporting metadata.

```markdown
# Defect: Refund retry charges twice

Severity: P1
Related Features: payments, refunds
Source: define
Source Feature: payments
Intake Request: c53012e6-631b-424b-9eb8-08bd5a3039ba

## Observed Behavior
A refund retry creates two charges.

## Expected Behavior
A retry preserves the original charge and creates no additional charge.

## Reproduction Steps
1. Submit a refund in the test environment.
2. Repeat the same request with its original idempotency key.
3. Inspect the charge count.

## Additional Context
Code-review finding from task 4. Reproduction steps supplied by the filer.

## Provenance
Source finding: finding-retry
Evidence: .speed/features/payments/evidence/structured_review/4/attempt-uuid.json
Filing decision: c53012e6-631b-424b-9eb8-08bd5a3039ba
Filed by: Alex <alex@example.test> at 2026-09-21T18:00:00Z
```

**NEW intake constructor; existing shell builders unchanged** — `lib/defect_reports.py`:

```python
def initial_defect_state(
    source_spec: str, reported_severity: str | None, now: str,
) -> dict:
    return {
        "status": "filed",
        "severity": None,             # triage has not assessed severity
        "reported_severity": reported_severity,
        "defect_type": None,
        "complexity": None,
        "branch": None,
        "created_at": now,
        "updated_at": now,
        "source_spec": source_spec,
    }
```

Filing adds the following keys to that returned dict. Existing `defect_init` and `create_defect_state` behavior remains unchanged; their filed-state shape is compatible with this intake state and requires no migration.

```json
{
  "related_features": ["payments", "refunds"],
  "source": "define",
  "source_feature": "payments",
  "created_by": "alex@example.test",
  "modified_by": "alex@example.test",
  "intake": {
    "schema_version": 1,
    "request_id": "c53012e6-631b-424b-9eb8-08bd5a3039ba",
    "finding_id": "finding-retry",
    "evidence_ids": ["evidence-content-hash"]
  }
}
```

These are **additions**, not a replacement `state.json`. Existing Bash transitions preserve unrelated keys. The primary affected feature is `related_features[0]`; `source_feature` never participates in affected-feature filtering.

### Report row contract — NEW, reuses existing Define fields

`discover_defects` returns the following normalized rows. `DefineDefect` keeps its current `name`, `severity`, `status`, `description`, `impact`, and `filed_at` fields; the adapter maps `slug` to `name` and adds the report metadata. This avoids silently changing existing callers' field meanings.

```python
from typing import TypedDict

class DefectRowData(TypedDict):
    slug: str
    title: str
    severity: str                 # P0/P1/P2/P3/unknown
    status: str                   # existing pipeline value/untriaged/unknown
    description: str
    impact: str | None
    filed_at: str | None
    updated_at: str | None
    related_features: list[str]   # ordered, first controls unfiltered grouping
    source: str                   # origin: define/security/manual/unknown
    source_feature: str | None
    source_finding_id: str | None # intake provenance; report can deep-link back
    canonical_path: str | None
    related_files: list[str]      # existing context relevance consumer
    tags: list[str]               # existing context relevance consumer
    filed: bool                  # complete spec/state, with committed receipt if intake
    warnings: list[str]
```

`source` is defect origin, not evidence source. A Define-filed defect with code-review evidence has `source=define`; it does not have `source=code_review`. Legacy reports lacking origin stay Unknown. The report snapshot contains `schema_version=1`, `revision`, normalized `filters`, the ordered `rows`, `groups` as `{feature, slugs}`, and `totals` as `{total, active, closed, p0_p1, affected_features, unassigned}`. `affected_features` counts distinct nonempty related names; all other totals count rows. Filtered mode has `groups=[]`.

### Filesystem records — both single-player (SP) and multiplayer (MP)

**Both modes are supported.** `feature_shared()` is the existing Python method's name; it does not mean the caller requires multiplayer. In SP it returns the ordinary `.speed/features/<feature>` directory. Only MP adds the `shared/` directory.

**REUSE — existing path resolution, no changes to `paths.py`:**

| Existing API / artifact | Single-player path | Multiplayer path |
|---|---|---|
| `paths.feature_shared("payments")` — feature records | `.speed/features/payments/` | `.speed/shared/features/payments/` |
| `paths.feature_local("payments")` — runtime files and logs | `.speed/features/payments/` | `.speed/local/features/payments/` |
| `paths.defects_dir` — defect pipeline records | `.speed/defects/` | `.speed/shared/defects/` |
| Canonical defect report — same in both modes | `specs/defects/<slug>.md` | `specs/defects/<slug>.md` |

The existing resolver detects MP when `.speed/shared/` exists. Intake uses that resolver; it must not create `.speed/shared/` in an SP project or introduce a second mode switch.

**SP example** — feature `payments`, task `4`, defect `refund-retry-double-charge`:

```text
specs/defects/refund-retry-double-charge.md           # NEW: canonical bug report
.speed/
  features/payments/
    evidence/structured_review/4/<attempt-id>.json   # NEW: preserved source evidence
    findings.json                                  # NEW: grouping and human decisions
    logs/review-4.json                              # REUSE: current code-review output
  defects/
    refund-retry-double-charge/
      state.json                                   # UPDATE format: add intake metadata
      report.md                                    # REUSE format: pipeline report copy
      logs/                                        # REUSE: pipeline outputs
      evidence/<request-id>.json                   # NEW: later evidence attachments
    .intake/<request-id>/
      manifest.json                                # NEW: filing/recovery receipt
      report.md                                    # NEW: staged report bytes
      state.json                                   # NEW: staged initial state
```

**MP example** — the same feature, task and defect:

```text
specs/defects/refund-retry-double-charge.md           # SAME canonical location
.speed/
  shared/
    features/payments/
      evidence/structured_review/4/<attempt-id>.json # NEW: preserved source evidence
      findings.json                                # NEW: grouping and human decisions
    defects/
      refund-retry-double-charge/
        state.json                                 # UPDATE format: add intake metadata
        report.md                                  # REUSE format: pipeline report copy
        logs/                                      # REUSE: existing defect pipeline layout
        evidence/<request-id>.json                 # NEW: later evidence attachments
      .intake/<request-id>/
        manifest.json                              # NEW: filing/recovery receipt
        report.md                                  # NEW: staged report bytes
        state.json                                 # NEW: staged initial state
  local/features/payments/
    logs/review-4.json                              # REUSE: current code-review output
```

“REUSE format” means filing creates a new defect's files in the existing pipeline layout; it does not overwrite another defect's report or state. The MP local/shared split shown here follows current paths; this RFC does not relocate existing defect logs.

**Why these records are separate:**

| Record | Purpose | When written |
|---|---|---|
| Feature `evidence/.../<attempt-id>.json` | Preserve what Diagnose or code review reported. A tool run can produce evidence without any defect being filed. | When the source command produces an attempt; legacy evidence can also be archived when a user records a decision. |
| Feature `findings.json` | Record grouping and what a person chose to do: fix, file, verify, defer, dismiss, or link a duplicate. | On an explicit decision/grouping action or rework acknowledgment. |
| Defect `state.json`, `report.md`, `logs/` | Use the existing defect lifecycle and pipeline inputs/outputs. | State/report at filing; logs during subsequent pipeline work. |
| Defect `evidence/<request-id>.json` | Attach references to newer evidence to an already filed defect; do not copy the feature archive again. | Only after the user confirms an evidence attachment. |
| `.intake/<request-id>/` | Keep enough information to finish a filing after a crash between writing the canonical report and state. This is transaction bookkeeping in **both** modes. | Only when a filing/attachment transaction starts. Committed receipts are retained for retries. |

An **attempt ID** identifies a producer invocation. A **request ID** identifies a user mutation and its retries. They are different because several tool attempts may support one filed defect. V1 Diagnose/code-review evidence is task-scoped; `_feature` is reserved for a future feature-scoped input such as V2 Eval and is not another directory root.

Each new JSON artifact has `schema_version: 1`. Viewing the inbox/report, previewing or canceling a draft creates none of these records. The filing protocol below explains why staged copies are necessary and which files count as committed.

## Implementation

### 1. NEW/UPDATE — read and preserve actual evidence

Implement `read_findings(paths, feature) -> FindingView` and `publish_attempt(paths, feature, producer, task_id, payload, content_hash, commit, diff_hash) -> Path` in `lib/defect_findings.py`. `FindingView` contains `feature`, integer `decision_revision`, `findings`, and `warnings`. Publication is called by the existing source commands, not by queries.

An archive contains `schema_version`, `feature`, `producer`, `task_id`, UUID `attempt_id`, `created_at`, nullable `commit`, nullable `diff_hash`, original `content_hash`, the redacted source `payload`, normalized/redacted `items`, and the names of redacted fields. Artifact hashes refer to archived bytes, not original unsanitized output. Each item carries `item_key` and the source fields needed to construct `Evidence`; its artifact path/hash are added by the reader, avoiding a self-hashing JSON record. `content_hash` hashes the original producer bytes supplied to publication; it remains the same when legacy output is archived. Hash a canonical JSON array `[producer, task_id, item_key, content_hash]` to construct the evidence ID; the feature provides its namespace. Files are immutable. Also store integer `sequence`, allocated as one greater than the maximum existing sequence for that feature under the intake lock. Select the greatest sequence per producer/task; do not use timestamps or file mtime as identity. Concurrent attempts with the same sequence from different MP clones are conflicts, never silently ordered. Older attempts remain available for decisions and provenance.

| Producer | Read today | V1 normalization and recommendation |
|---|---|---|
| Diagnose | Shared `risk-surface.yaml` | Each nonempty class signal becomes unjudged evidence; retain the signal text as summary/supporting context plus `where`, task and class. Do not populate a draft's Observed Behavior from Diagnose. Recommend Investigate. Zero signals are not proof of passing. |
| Structured code review | Local `logs/review-<task>.json` | Consume `issues`, unsatisfied/partial `spec_verification`, `missing_from_spec`, and `out_of_scope`. Major/critical or request-changes recommends Fix in this feature; out-of-scope recommends Fix/revert scope. |
| Clean-context code review | Shared `reviews/task-<task>.review` | New output must satisfy clean-review schema version 1 and uses the same normalizer. Pre-contract compatibility files remain readable as structured JSON or one text artifact with unknown verdict and incomplete draft fields. |
| Eval | **V2 only** | Adapter supplies executed scenario results; contract below. |

**NEW normalization code**, used by both structured code-review input modes:

```python
def review_items(payload: dict) -> list[tuple[str, dict]]:
    result = []
    for field in ("issues", "spec_verification", "missing_from_spec", "out_of_scope"):
        values = payload.get(field, [])
        if not isinstance(values, list):
            raise ValueError(f"{field} must be an array")
        for item in values:
            if isinstance(item, str):
                item = {"description": item}
            if not isinstance(item, dict):
                raise ValueError(f"{field} entries must be objects or strings")
            if field == "spec_verification" and item.get("satisfied") in (True, "true"):
                continue
            result.append((field, item))
    return result
```

Array-specific conversion maps `message`, `description`, or `spec_quote` to a source-labeled summary. It populates Observed Behavior only from an explicit `observed` or `actual` field. It populates Expected Behavior from explicit `expected`, or from `spec_quote`/`requirement` on `spec_verification` and `missing_from_spec`. It populates Reproduction Steps only from explicit `reproduction` or `repro`. A suggestion is not an expected behavior unless the user confirms it. Derive affected files only from explicit file fields.

**UPDATE source writers:** capture the actual inspected branch commit and diff digest before invoking the existing engine/reviewer; publish the resulting attempt before overwriting the existing compatibility output. Retain both original command contracts and review verdict processing. On publication failure, report the error and preserve the prior compatibility output. Do not add authoring context to clean-context review. `agents/clean-context-reviewer.md` owns its behavior and versioned output contract; `review.sh` supplies only runtime metadata and the diff. `lib/review_evidence.py` strictly validates current output, while its explicit legacy mode keeps pre-contract artifacts readable. Diagnose receives normalized engine JSON directly; its rule engine needs no change.

When an archive exists for a producer/task, do not also ingest its compatibility file as another attempt. While publishing under the intake lock, snapshot any pre-upgrade compatibility output once before replacing it, so an existing decision cannot lose its only source. Legacy files remain readable without migration. Earlier attempts already overwritten before this change cannot be reconstructed. Before committing a decision or filing against a legacy file, validate the submitted revision, archive its normalized/redacted contents under the write lock, then persist archive references. This changes the storage path/hash, not the evidence ID. Never persist a new decision whose only provenance is an overwritable compatibility file. Parse legacy Diagnose YAML with `yaml.safe_load`; add PyYAML to the existing requirements. A headless installation lacking it gets a source warning, while code-review/report inspection continues. Hash the bytes actually read; missing task/commit/attempt values remain unknown. Do not infer inspected commit from the current checkout. Malformed, missing, unsupported, or oversized individual sources produce warnings without hiding valid sources. Exclude `review-nits.json` from task-artifact discovery.

### 2. NEW — correlate and record decisions

The core owns grouping, revisions, recommendations, and available actions. The frontend only renders the result. Reading builds an index once by source identity and once by explicit issue key, then applies saved groups. Sorting and display never alter IDs.

`record_decision(paths, feature, decision_revision, finding_revision, input, actor) -> Decision` reloads the current view under the intake lock, checks both revisions, validates the action, appends the decision, and atomically replaces `findings.json`. An identical request UUID/body returns the original decision; the same UUID with a changed body returns `REQUEST_CONFLICT`.

| Action | Required validation | What changes |
|---|---|---|
| Fix in this feature | Existing task in this feature; rationale or task link | Append decision and queue rework; no defect. |
| Create defect | Rationale, completed draft, explicit severity confirmation | Only filing commits the decision; preview is read-only. |
| Needs verification | Rationale | Append decision; finding remains unresolved. |
| Accept/defer | Rationale | Append decision; does not alter any feature/test/approval result. |
| False positive | No rationale required | Append decision; contradictory newer evidence invalidates it. |
| Duplicate | Existing finding or defect target; reject self/cycles | Append link; target lifecycle remains authoritative. |

`group_findings(paths, feature, decision_revision, memberships, rationale, actor, request_id) -> FindingView` validates all member identities and rejects assigning one member to multiple groups. It appends grouping history and increments the revision under the same lock. Return current evidence unchanged.

**UPDATE `tasks.sh` and `cmd/run.sh`, only for requested rework:** consume queued decisions immediately after `speed_acquire_lock("run")`, before scheduling. Reuse `task_request_changes`; add an optional third request-ID argument that writes `finding_rework_request_id` in the same atomic task update. Existing two-argument calls are unchanged. A matching marker means the request was already applied, even if the process crashed before acknowledging it in `findings.json`. Process one request and persist its acknowledgment before advancing to the next. Hold the intake lock only for selecting/acknowledging queue entries; the run lock covers the task write.

If task status is already pending with `review_verdict=request_changes`, retain its existing feedback and add the request marker; the finding history keeps the additional guidance. A pending task without that verdict stays pending and receives the linked guidance through the same task helper. If done, queue through `task_request_changes`. Failed/blocked/running or missing tasks produce a blocked rework record with an explanation; do not reset them silently. The UI distinguishes Queued, Applied, and Blocked. No agent or command runs on a dashboard click. Rework remains unresolved until a newer structured review of that task approves, the current task still has `review_verdict=approve` (so a later Guardian rejection is respected), and the issue is absent; clean prose or a missing artifact cannot auto-resolve it.

### 3. NEW/UPDATE — share defect parsing and reporting

`lib/defect_reports.py` owns these contracts. Bodies not shown here implement the explicitly listed parsing/projection rules; there is no second parser in GraphQL or React.

| Function | Return and behavior |
|---|---|
| `parse_report(text: str) -> dict` | `title`, nullable `severity`, ordered `related_features`, `source`, nullable `source_feature`, `observed`, `expected`, `reproduction`, `context`, `related_files`, `tags`, nullable `intake_request_id`, and `warnings`. No I/O. |
| `validate_report(report: dict, strict: bool = False) -> list[dict]` | Errors as `{field, message}`. Strict mode enforces filing rules; compatibility mode preserves current shell requirements/warnings. |
| `render_report(draft: dict, provenance: dict) -> str` | Existing defect-report sections plus plural affected features and provenance shown above. |
| `discover_defects(root: Path, defects_dir: Path) -> list[dict]` | One row per unioned canonical/state slug, with explicit metadata warnings and transaction readiness. |
| `build_report_view(rows: list[dict], filters: dict) -> dict` | One filtered/sorted/grouped snapshot; includes revision, filters, rows, groups, totals, and warnings. |
| `export_report(view: dict, format: str) -> str` | Serialize that exact snapshot as JSON or escaped Markdown. Does not rediscover files. |

Parser behavior:

- Accept plain/bold metadata, severity suffixes such as `P1-high`, singular/plural Related Feature(s), comma-separated feature names, and existing Markdown spec links. Read the whole metadata region, not the first ten lines.
- Support both inline behavior labels and section bodies from `templates/defect-report.md` and `templates/defect.md`. Ignore comments, fenced examples, and template placeholders as actual field values. Preserve multiline content.
- Normalize a linked `specs/product/payments.md` to `payments`; preserve affected-feature order and remove duplicates. Parse optional YAML frontmatter arrays with the same safe loader.
- Strict filing requires at least one known feature. Legacy unknown features remain visible with warnings; missing affected features go to Unassigned. Never fall back from Related Features to Source Feature.
- Preserve legacy aliases `critical`, `major`, `minor` for the context adapter. Do not silently equate them to a P-number in the manager report.

**UPDATE/DELETE:** replace extraction bodies in `defects.sh`, Define's three defect helpers, and the discovery/parser portion of `context.py::read_defects`. Keep shell function names, exit codes, stdout contracts, and contextual file/tag relevance. `parse_defect_report` still emits its existing key/value fields; use a new JSON output mode for multiline/new consumers rather than interpreting those values as shell code. `defect_resolve_specs` returns existing product/tech spec paths for every Related Feature. Triage consumes that list; the fix-stage related-feature guard uses the same parser.

**Report field precedence** is deterministic:

| Field | Order |
|---|---|
| Slug | Canonical basename / state directory name; never an unchecked `state.name` path |
| Title, description | Canonical Markdown, then state description/name |
| Status | State status; `untriaged` if spec-only; `unknown` if malformed |
| Severity | Valid triaged `severity`, valid `reported_severity`, valid report severity, then `unknown` |
| Related Features | Explicit canonical metadata, then state mirror if absent; explicit empty metadata remains empty |
| Source | Explicit report metadata, then state source, then `unknown` |
| Source Feature | Explicit report/state provenance only |
| Updated/filed time | Valid state timestamps; absent remains null |
| Canonical link | Existing validated canonical path; null with warning if missing |

Conflicting values produce a warning even when precedence selects a usable value. Malformed state does not hide its canonical report. Pending intake records appear as Repair required with `filed=false`, never as successful filings. Existing records without intake metadata remain valid legacy inventory.

**NEW filter code** (row fields use snake_case internally; GraphQL maps to camelCase):

```python
CLOSED = frozenset({"resolved", "rejected"})

def lifecycle(status: str) -> str:
    return "closed" if status in CLOSED else "active"

def matches(row: dict, filters: dict) -> bool:
    affected = set(row["related_features"]) or {"_unassigned"}
    if filters.get("features") and not affected.intersection(filters["features"]):
        return False
    for field in ("severity", "status", "source"):
        if filters.get(field) and row[field] not in filters[field]:
            return False
    if filters.get("lifecycle") and lifecycle(row["status"]) not in filters["lifecycle"]:
        return False
    needle = filters.get("search", "").strip().casefold()
    return not needle or needle in f'{row["title"]} {row["slug"]}'.casefold()
```

Sort by severity P0→P3→Unknown, descending update time (null last), then slug. Count unique rows after filtering. With no feature selection, group once under the first affected feature or Unassigned; with any feature selection, return one flat list. Multi-select values OR within a filter and AND across filters. `escalated`, `fixed`, `reviewed`, and `integrating` all remain Active.

The same view powers Define, the dedicated report, CLI, JSON and Markdown. Dashboard export supplies the displayed revision; if files changed, return `STALE_REPORT` and require refresh rather than exporting a different result. Read each input once per request; no per-row feature scans and no write-on-read cache.

### 4. NEW — preview, file, and recover (`lib/defect_intake.py`)

The editable draft is small. It exists only in the API response and browser state until the user files.

```python
@dataclass(frozen=True)
class DefectDraft:
    title: str
    severity: str | None          # P0/P1/P2/P3; user must confirm
    severity_confirmed: bool
    related_features: tuple[str, ...]
    observed: str
    expected: str
    reproduction: str
    context: str
```

`preview_defect(paths, feature, finding_id) -> dict` returns `{draft, source_feature, finding_revision, decision_revision, provenance, missing_fields, duplicates}`. Source feature and provenance are server-owned, never writable draft fields. Combine source facts deterministically with source labels. Diagnose is supporting context, not an observed execution failure. Do not fill absent facts from task descriptions or an LLM. Retain a user's edits on errors; Refresh evidence asks for confirmation before replacing the current draft with a newly generated preview.

`file_defect(paths, feature, finding_id, evidence_ids, finding_revision, decision_revision, request_id, draft, rationale, actor, duplicate_reason=None) -> dict` returns `{slug, canonical_path, decision_id, replayed}`. The request digest includes feature, finding, submitted evidence IDs, draft, rationale, duplicate reason, and server actor. Revision tokens are checked for freshness but excluded from that digest; changing selected evidence or form values after staging still conflicts. Same request/body replays the existing result; changed body with the same request conflicts. Require `evidence_ids` to match the selected finding members at the submitted revision; the server reloads their facts and never accepts client-authored provenance. Exact already-filed identities return the existing defect. Weaker matches return duplicate candidates; a separate filing requires a recorded reason. A resolved defect's regression is a new linked defect, not a silent reopen.

**Validation before any write:** title 1–160 characters; slug matching `^[a-z0-9]+(?:-[a-z0-9]+)*$`, max 80, with long slugs shortened only at a word boundary (or a deterministic fallback when no boundary exists); severity explicitly confirmed; non-placeholder observed/expected/reproduction; 1–20 known affected features; rationale nonempty; all text fields at most 16 KiB; total generated report at most 128 KiB. Feature names use the existing lowercase/hyphen, max-50 rule. Read a source artifact only within project roots and at most 1 MiB; preserve warning details. Reject traversal, symlink escape, absolute artifact references, and both existing canonical paths and state directories.

**Verified limitation:** there is no callable draft/text scanner. `grounding_check_secrets(task_id, worktree_path)` scans a task branch and writes logs; calling it would not validate this draft.

**UPDATE, narrowly scoped:** extract its existing pattern-selection block into `_secrets_pattern_pairs()` in the same `grounding.sh` file. It emits pattern-name/tab/POSIX-ERE pairs; the current scanner reconstructs its two arrays from that helper. The intake adapter sources existing config/grounding in a fixed shell script, gets those pairs, and applies `grep -qE -e` to report bytes on stdin. Never interpolate report text into shell code or return matched contents. A scanner/invalid-regex error blocks filing; exit 0 means match and exit 1 means no match. This is the sole utility edit outside defect handling: it prevents copying a second list of security rules. No new pattern file, scanner framework, or task-gate behavior change.

Auto-generated context includes selected structured fields and inert references, never full log bodies. Define `secret_fields(fields: dict[str, str]) -> set[str]` once in `defect_reports.py` using that adapter; both the evidence publisher and intake use it. Before archiving selected source fields into shared storage, replace flagged fields with `[redacted: source contains a credential pattern]` and record only field names in warnings. Retain an original-content hash, not the raw secret. Such fields are incomplete for drafting and must be supplied by the user. Sensitive raw logs remain local path references. The scanner cannot prove arbitrary prose contains no personal data; the editable preview remains required.

**Transaction algorithm:** two separate filesystem destinations cannot be committed with one rename. This design guarantees logical filing atomicity to the intake/report/CLI readers, with explicit crash recovery. It does not pretend raw filesystem observers cannot see an intermediate file.

1. Acquire the defect intake lock. Look up request/body digest first. If already committed, return the prior result before stale checks. Otherwise recheck revisions, destination collisions, duplicate identities, and scanner results. When a task and inspected commit are recorded, resolve the task's current branch commit; a moved branch makes the draft stale. The archived diff hash remains provenance and is not recomputed with a different source-command algorithm. Unknown legacy identity remains visibly unknown. No fabricated “current build” comparison.
2. Stage exact report/state bytes and a versioned manifest under `.intake/<request-id>/`. The manifest records request/body digest, feature/finding, decision, destination paths, byte hashes, and phase `prepared`. Fsync staged files and directory before publication.
3. Publish the canonical report without replacement. Reserve the final defect directory with exclusive `mkdir`, then publish its report/state and create logs. These individual publications are not a single atomic operation. The report includes Intake Request; state includes the same ID. Never overwrite an unrelated file, even if its slug matches.
4. Atomically append the decision to `findings.json`, keyed by request ID. Until step 5, readers suppress that decision's filed status and report the transaction as incomplete.
5. Atomically set manifest phase `committed` and fsync it. This is the logical commit point. Only now does the API return success; the existing registry is updated afterward as a retryable cache operation.

Use `fcntl.flock` on `<defects-dir>/.intake.lock` plus a process-local `threading.RLock`. Fail with `BUSY` after 5 seconds; never wait indefinitely in a resolver. Use the same lock for finding decisions, grouping, artifact publication, and filing's final checks; never hold it during model invocation. Reads do not create lock files. Serialize in-process writers as well as separate processes. Existing ceremony claim locks and execution locks remain unchanged.

To obtain a consistent read without creating a lock file, capture feature/manifest/source revision tokens before and after assembly and retry on changes, at most three times; then return `BUSY`. If a consumer holds the run lock and needs the intake lock, acquire them in that order; intake mutations never acquire the run lock.

Readers derive readiness from the matching manifest. A missing/corrupt manifest for an intake-tagged record is Repair required; it must not be accepted as a legacy record. `cmd_defect`, triage, Define and context use the same readiness check. Both existing shell state-read entry points delegate to it for intake-tagged records, so `run --defect`, `retry --defect`, and `integrate --defect` cannot bypass readiness through their existing state-reader calls. Editor may expose an existing report as text, but that does not imply a completed filing.

On failure, return `WRITE_FAILED` or `REPAIR_REQUIRED` and retain the same request ID. A staged transaction freezes its submitted body: Retry repairs that body. Edited draft fields require a new request ID only after the previous request is confirmed unpublished/aborted; an incomplete published transaction must first be repaired. Validation failures before staging reserve nothing, so edits remain possible.

Retry resumes only byte-identical artifacts owned by that request; foreign/edited destinations return `RECOVERY_CONFLICT`. If nothing was published, discard staged payloads explicitly. After any publication, roll forward on explicit Retry/Repair; read-only operations never recover implicitly. Recovery merges the missing decision into the latest history rather than replacing it with a stale staged feature file. Keep committed manifests as receipts. Deleting them would destroy readiness/idempotency evidence.

`append_defect_evidence(paths, feature, finding_id, defect_slug, finding_revision, decision_revision, request_id, rationale, actor) -> dict` follows the same staged/committed protocol for a versioned `evidence/<request-id>.json` entry and decision history. The history entry has `event_kind=evidence_attachment`, `action=null`, and the linked defect/evidence IDs. It preserves the canonical report, initial report snapshot, severity and lifecycle. Attach current evidence only after confirmation.

### 5. UPDATE — feed the existing defect pipeline

**UPDATE `lib/cmd/defect.sh`**: move file/path validation ahead of existing-state dispatch. Resolve paths with path-component containment, not a string-prefix check. Check intake readiness and that `source_spec` resolves to the supplied report. Add an explicit unknown/in-progress status error instead of printing success by falling through.

**NEW helper in the existing command file; UPDATE two call sites.** This factors the current fresh-report tail so the new `filed` branch does not duplicate triage/routing or fall through to the old unconditional success message.

```bash
# NEW in lib/cmd/defect.sh. Args: report path, validated defect name.
_defect_start_triage() {
    local spec_path="$1" name="$2" triage_rc=0
    triage_defect "$spec_path" || triage_rc=$?
    if [[ $triage_rc -eq 0 ]]; then
        fix_defect "$name" || return $?
        integrate_defect "$name" || return $?
        log_success "Defect '${name}' resolved"
    fi
    # Preserve current routing: triage returning 1 can mean the human stop,
    # rejection, or escalation. Changing that legacy return contract is separate.
}
```

```diff
# UPDATE inside cmd_defect's existing-state switch:
         case "$status" in
+            filed)
+                _defect_start_triage "$spec_path" "$name"
+                return $?
+                ;;
             resolved|rejected|escalated)
                 log_info "Nothing to do"
                 return 0
                 ;;
# Existing explicit resumable-state handlers remain here.
+            *)
+                log_error "Cannot resume defect '${name}' from '${status}'"
+                return 1
+                ;;
         esac
```

**DELETE** the current fresh-run tail (`local triage_rc=0` through its final `if`) and **REPLACE** it with `_defect_start_triage "$spec_path" "$name"`. Validate intake readiness and source identity before this switch. This fixes pre-filed entry without changing moderate triage into automatic fixing. The existing ambiguity between triage failure and a deliberate human stop remains a documented legacy limitation; this RFC does not promise a new exit-code contract.

**UPDATE `triage_defect` initialization only:** if no directory exists, use `init_defect_dir` + `create_defect_state` as today. If one exists, require status `filed`, valid matching source/report, complete initial state, and committed intake receipt when present; then skip initialization. Any mismatch fails without modifying either record. Continue through the existing `filed → triaging` transition and unchanged investigation/classification/routing.

**UPDATE `speed` startup:** refresh `DEFECTS_DIR` immediately after MP detection through one `_defect_refresh_root` helper in `defects.sh`, also used at source time for standalone shell consumers. This keeps dashboard filing and CLI processing on the same shared defect directory.

**REUSE unchanged:** branch naming, provider prompts, reproduce/fix/review/integrate orchestration, gates, and lifecycle transitions. Resolution still happens only through existing integration behavior. Filing never launches triage.

## API Surface

### NEW — GraphQL adapters

Add defect-specific resolver/types modules and register their fields in the existing schema. The resolver obtains `project_root` and actor from server context, passes `get_paths(project_root)` into the core, and maps snake_case to Strawberry camelCase. No direct filesystem/parser logic in resolvers.

| Operation | Inputs | Result |
|---|---|---|
| `featureFindings` query | `featureName` | FindingView: revisions, findings, history, warnings, actions |
| `evidenceFile` query | feature, finding, evidence ID, exact declared source path | Bounded read-only UTF-8 excerpt with line range; undeclared, escaping, Git-internal, environment, binary, and oversized paths are rejected |
| `defectDraft` query | `featureName`, `findingId` | No-write preview described above |
| `defectReport` query | filters | Snapshot: revision, rows, groups, totals, warnings |
| `defectReportExport` query | filters, displayed revision, format | Exact-view JSON/Markdown content or `STALE_REPORT` |
| `decideFinding` mutation | feature, finding, revisions, request ID, action, rationale, optional task/duplicate target | Decision |
| `groupFindings` mutation | feature, revision, request ID, memberships, rationale | Refreshed FindingView |
| `fileFindingDefect` mutation | typed filing input below | Canonical link, slug, decision ID, replayed flag |
| `appendDefectEvidence` mutation | feature, finding, revisions, request ID, target slug, rationale | Evidence entry link and decision ID |

```graphql
input DefectDraftInput {
  title: String!
  severity: String!
  severityConfirmed: Boolean!
  relatedFeatures: [String!]!
  observed: String!
  expected: String!
  reproduction: String!
  context: String!
}
input FileFindingDefectInput {
  featureName: String!
  findingId: String!
  evidenceIds: [String!]!
  findingRevision: String!
  decisionRevision: Int!
  requestId: String!
  draft: DefectDraftInput!
  rationale: String!
  duplicateReason: String
}
type DefectFieldError { field: String!, message: String! }
type FileFindingDefectResult {
  success: Boolean!
  code: String!
  errors: [DefectFieldError!]!
  slug: String
  canonicalPath: String
  decisionId: String
  replayed: Boolean!
}
```

All mutations use the same result convention: `success`, `code`, field `errors`, nullable success payload. Codes are `OK`, `NOT_FOUND`, `INVALID_INPUT`, `STALE_EVIDENCE`, `STALE_DECISION`, `STALE_REPORT`, `DUPLICATE`, `PATH_EXISTS`, `REQUEST_CONFLICT`, `BUSY`, `WRITE_FAILED`, `REPAIR_REQUIRED`, and `RECOVERY_CONFLICT`. A filesystem write-permission error maps to `WRITE_FAILED`; no ceremony ratification permission is treated as release authority. Paths and commands from evidence are never subprocess instructions. Artifact/log paths remain inert references. An explicitly declared source file may request a bounded excerpt through `evidenceFile`; the shared core revalidates evidence membership, resolved project-root containment, file kind, encoding, and size before reading.

### NEW/UPDATE — CLI

`lib/cmd/define.sh` delegates to `python -m lib.define_cli` using the existing SPEED Python selection and package root. Python imports `dashboard.backend.paths` only for its existing stdlib path resolver, not the dashboard server or Strawberry. The core receives those paths; it does not import ceremony/server modules.

```sh
speed define feature payments                 # summary + existing dashboard if available
speed define feature payments --no-open
speed define feature payments --json
speed define defects
speed define defects --feature payments --feature refunds --lifecycle active
speed define defects --severity P1 --status filed --source define --format markdown
```

Dispatch `define` before the existing global argument loop, so repeated feature filters reach its own parser and read-only invocation bypasses the roster heartbeat. That parser still honors `--json`, verbosity, and `--no-open`; invalid flags fail explicitly. Do not call `_require_feature`, `feature_activate`, dashboard start/ingest, or the status function that deletes stale PID files. Feature existence is the same runtime/product-spec union Define already uses; extract only its name-discovery loop into `defect_reports.py` and reuse it in the old adapter.

Reuse `DASHBOARD_DIR`, `DASHBOARD_FRONTEND_PORT`, and `_dashboard_api_alive`; check the existing frontend PID without modifying it. Browser opening is limited to terminal output in a TTY with a running frontend. JSON/Markdown never opens a browser. No dashboard process is started automatically. Reuse one `build_report_view` result for terminal and export output.

## Dashboard changes

**NEW** `/define/[feature]/findings` composes existing Header, IconRail, ErrorBoundary, KPI, buttons, dropdown/popover and toast primitives. It owns query/filter state and renders findings with source labels, evidence disclosure, decisions, merge/split and an editable defect drawer. **NEW** `/define/defects` displays the server's groups/rows/totals with URL-backed filters and export controls.

**UPDATE** existing Define pages with entry links. The feature Findings link must be available before context-package/BLUF/ceremony early returns; evidence inspection must work for a spec-only feature. Do not repurpose `/define/[feature]/review`.

**REUSE** `DefectRow`: extend it with canonical links/affected-feature metadata and a table-row rendering mode for the report; retain its compact/grid use on Define. Keep shared defect presentation in this component rather than adding a second report-row implementation. The report page renders table headers and supplies pre-sorted rows; it does not recompute grouping or totals.

**NEW** drawer uses a native modal dialog with existing tokens/utilities: labeled fields, trapped focus, Escape/cancel, focus return, inline field errors, and unsaved edits retained on stale/duplicate/write failures. No shared CSS or UI-library change. No draft file/local-storage persistence; cancel is zero-write. New report filters use repeated URL keys, preserve browser back/forward history, and select Related Features with exact matching.

**UPDATE** editor hydration: after restoring the saved session, validate `?path=specs/defects/<slug>.md`, then call existing `openSpec(path)` and choose preview. The URL-selected document wins over saved active-tab state without discarding existing tabs. Validate a return URL against local Define routes only. Missing canonical files show a metadata warning instead of an invented link. After filing, call existing `update_spec`; cache failure warns/retries indexing without undoing a committed defect.

## V2 — Eval as an input

Eval joins the same evidence → finding → decision → draft flow. It is not another review/approval system. **No Eval implementation or Eval handoff file is part of V1.** The V2 adapter converts the actual Eval producer's results into `Evidence` and adds the execution fields below; its filesystem/transport integration is selected when that producer exists.

```python
# V2 proposal only: normalized INPUT at the adapter boundary.
@dataclass(frozen=True)
class EvalResult:
    result_id: str
    run_id: str | None            # absent if Eval never started
    scenario_id: str
    task_id: str | None
    requirement_ids: tuple[str, ...]
    issue_key: str | None
    status: Literal["pass", "fail", "partial", "unverifiable", "blocked", "not_run"]
    required: bool
    commit: str | None
    build_fingerprint: str | None # absent for blocked/not-run inputs
    observed: str | None
    expected: str | None
    command: str | None
    log_paths: tuple[str, ...]
    trace_paths: tuple[str, ...]
    upstream_result_id: str | None
```

| V2 input | Intake behavior |
|---|---|
| Fail with run/build identity | Execution-backed candidate; prefill actual/expected/command with attribution. Still require human filing/severity. |
| Partial | Isolate missing behavior before filing. |
| Unverifiable | Needs verification, not proof of a product defect. |
| Blocked | Link the upstream cause; avoid duplicate downstream defects. |
| Not run | Operational recovery, not a product bug. |
| Pass | Can resolve an earlier execution failure only for the same scenario against the relevant newer build. |

V2 extends `Evidence.confidence` with `execution_confirmed` and `verification_gap` alongside an optional execution record containing the Eval fields above; existing V1 archives remain readable.

V2 correlation uses explicit shared issue identity or manual linking, not just a shared scenario/requirement. Preserve run/build/required/result status as source facts. Filing never changes the Eval result or clears its failed-required status. Execution-confirmed confidence requires nonempty run ID, commit and build fingerprint plus an actual failed execution result. Unknown or malformed identity cannot earn that label. V1 parsers encountering an unsupported future archive version report it as unsupported and never overwrite it.

V2 tests will cover a failed run prepopulating a draft, repeated scenarios linking existing defects, old-build stale checks, blocked/not-run routing, and failed-required results staying failed after filing. These tests and the Eval adapter are excluded from the V1 LOC table.

## Testing and acceptance

This change needs integration tests at the file/pipeline boundary; merely testing dataclass fields would miss its main failure modes. Reuse the existing defect shell test harnesses and Define/context fixtures. Run tests against temporary project roots, with provider calls stubbed.

| Acceptance / failure mode | Required test | PRD stories |
|---|---|---|
| Source meaning and history | Normalize both review modes and Diagnose; rerun retains prior attempt; bad source leaves valid findings usable; absent Eval is not a V1 warning. | S1–S3, S9 |
| Identity and decisions | Stable exact identity across attempts, conservative cross-source grouping, merge/split with history, stale dismissal on changed evidence. | S3–S4, S10, S13 |
| Rework | Existing pending task retains review feedback; done task goes pending via existing helper; crash after task update replays without resetting executed work; blocked/missing task stays unchanged. | S5 |
| Draft quality | Missing expected/repro/severity/affected feature blocks; no automatic P0; source feature immutable; secret match blocks; preview/cancel create no files. | S6–S8, S12, S17–S18 |
| Filing and recovery | Duplicate clicks/processes produce one defect; fault after every publication step never reports a partial filing as successful; retry preserves the original decision and foreign edits. | S9–S10, S17 |
| Existing pipeline | Dashboard-filed report reaches triage exactly once in SP and MP; moderate triage pauses; invalid/mismatched/pending intake refused; integration still owns resolution. | S17, S19 |
| Manager report | Both templates, inline/section fields, plural/link features, unknown/malformed metadata, conflicts, state-only/spec-only and overlapping features produce one row per slug. | S15, S18–S19 |
| Filters/export | Any-feature matching, AND across filters, source-vs-affected distinction, stable ordering, displayed-revision export, Unknown/Unassigned and closed categories. | S15–S16, S19 |
| Read-only entry | Hash project files before/after CLI/queries/export; no feature initialization, migration, heartbeat, PID cleanup, or repairs. Repeated `--feature` survives CLI dispatch. | S1, S15–S17 |
| UI | Drawer keyboard/focus/errors, stale edits retained, canonical editor link wins hydration, browser filter history; views at 390/768/1440px. | S6–S8, S14–S16 |
| No outcome mutation | Filing/defer leaves feature state, ratification and code-review verdict files byte-identical. V2 separately tests Eval status. | S11 |

Performance acceptance: local fixture of 50 tasks with 50 Diagnose and 50 code-review attempts, and a separate 20-feature/500-defect inventory, returns each read in under 2 seconds. Record the machine and cold/warm measurements. The product's additional 200 Eval results belong to the V2 benchmark.

Implementation verification commands (filenames match the measured impact table):

```sh
.venv/bin/python3 -m pytest \
  tests/test_defect_reports.py tests/test_defect_findings.py tests/test_review_evidence.py \
  tests/test_defect_intake.py tests/test_define_cli.py tests/test_rework_cli.py \
  dashboard/backend/tests/test_feature_defects.py
.venv/bin/python3 -m pytest dashboard/backend/tests/test_context.py
.venv/bin/python3 dashboard/backend/tests/test_define_types.py
bash tests/test_defect_state.sh
bash tests/test_defect_cli.sh
PATH="$PWD/.venv/bin:$PATH" bash tests/test_diagnose_cmd.sh
PATH="$PWD/.venv/bin:$PATH" bash tests/test_review.sh
bash tests/test_tasks.sh
bash tests/test_secrets_scanner.sh
bash tests/test_grounding_secrets_integration.sh
npx --prefix dashboard/frontend eslint \
  'app/define/[feature]/findings/page.tsx' 'app/define/defects/page.tsx' \
  'app/editor/page.tsx' 'components/define/defect-row.tsx' \
  'lib/graphql/queries/feature-defects.ts'
npm --prefix dashboard/frontend run build
```

Recorded on 2026-09-21 on the implementation checkout:

- 24 new core/CLI/GraphQL tests passed.
- 147 reused shell tests passed: defect state/CLI, task transitions, Diagnose, Review, grounding, and secret scanning.
- Modified frontend files passed ESLint with zero errors. The production bundle compiled those files, then the repository-wide build stopped at the pre-existing `dashboard/frontend/components/editor/IntelPanel.tsx:332` subscription type error.
- The context suite passed 115 tests and retained two pre-existing failures expecting a `synthesis` progress event. The full frontend suite passed 232 tests and retained 58 unrelated landing/ceremony failures.
- A cold local fixture assembled 100 V1 source attempts in 0.0298 seconds and discovered/parsed/grouped 500 defects in 0.0900 seconds. These are local measurements, not cross-platform guarantees.

## Delivery order and constraints

1. Shared defect parser/intake-state constructor/inventory with legacy characterization tests. Then switch only the duplicate report readers; keep the existing shell state builders.
2. Existing-source archival, findings/decisions, read-only CLI/report and UI entry points. No migration runs on reads.
3. Draft, transaction/recovery, and `filed` CLI/triage compatibility together. Enable filing only when crash/concurrency and SP/MP pipeline tests pass.
4. Rework queue and later evidence attachment; complete keyboard/filter/export/end-to-end coverage.
5. V2 adds the Eval adapter against its implemented producer. No V1 dependency on a fictional handoff.

All writers are local processes sharing one checkout. Git synchronization between separate MP clones is not a distributed transaction protocol; divergent finding histories or colliding canonical reports must surface as merge conflicts. Existing report/state files require no bulk rewrite. Rollback must retain intake receipts and the filed-state resume/readiness changes for already-created defects.

Remaining tradeoffs are deliberate: importing the existing path module from a headless adapter is less architectural churn than relocating it; conservative matching can require manual grouping; immutable evidence consumes disk; two-destination filing needs a recoverable journal. None justifies changes to ceremony, Learn, or release approval. The one grounding edit is limited to sharing its existing secret-pattern list; the task scanner itself keeps its behavior.
