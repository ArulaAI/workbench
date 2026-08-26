# RFC: Workbench Skill System

> See [speed-skill-system-prd.md](../product/speed-skill-system-prd.md) for the source PRD.
> Feature note (authoritative product scope): [define-module/01-skill-system.md](../product/define-module/01-skill-system.md).
> Reference architecture (local, read-only): `../forge-foundry-primitives/forge_sync/`.

This RFC specifies the technical design for the Workbench Skill System: a canonical skill catalog, a lean stdlib Python projection engine, managed-file identity, the `workbench` command namespace with temporary `speed` aliases, and `workbench-hello` as the platform proof skill. It aligns with the updated feature note, which reframes the skill system as a Workbench-wide platform (used by every module, not only Define) and sets a strict bootstrap order: prove the platform with a helper-backed `workbench-hello` before any module skill such as `workbench-draft` ships.

Scope here is packaging, projection, routing, and lifecycle. Domain workflow behavior (the `workbench-draft` interview, etc.) is owned by the module notes and is not defined here.

## What changed from the previous revision

This RFC previously targeted `speed skills` and shipped `workbench-draft` first. The updated note changed two foundational decisions, and this revision follows them:

| Dimension | Previous RFC | This revision (matches the note) |
|---|---|---|
| First skill | `workbench-draft` (agent-native placeholder) | `workbench-hello` (helper-backed shared-implementation proof) |
| Command namespace | `speed skills …` | `workbench …` canonical; `speed …` retained only as labeled temporary aliases |
| Framing | Define feature | Workbench platform service for all modules |
| Added scope | (none) | skill identity/versioning, release change ledger, project install-event log, compatibility/regression gate |

## Basic Example

The platform proof skill is intentionally the smallest possible package. It is helper-backed: one canonical `scripts/hello.py` is the single implementation both the CLI and the agent route execute.

```text
skills/workbench-hello/
├── SKILL.md          # invocation + safety contract; no domain logic
└── scripts/
    └── hello.py      # the ONE greeting implementation (stdlib)
```

Both entry points resolve the same canonical package and run the same helper:

```console
$ workbench init
✓ Skills projected: 2 skills → .claude/skills/ (claude_code)

$ workbench hello Mohit
skill: workbench-hello
message: Hello, Mohit! Workbench skills are available.
catalog_version: 0.1.0
surface: workbench-cli

$ workbench skills status
catalog 0.1.0 · 2 skills
  claude_code   workbench-hello   current
  claude_code   workbench-draft   current
```

Inside Claude Code the user invokes `/workbench-hello Mohit`; the projected `SKILL.md` runs the same `scripts/hello.py`. `speed hello`, `speed init`, and `speed skills …` remain as temporary aliases that route to the identical implementation and print a one-line notice naming the canonical `workbench` command.

## Data Model

Four artifacts: the canonical package, the projection, the manifest, and the append-only logs.

### Canonical package (source of truth)

Lives at `${SPEED_DIR}/skills/<skill-name>/`. One directory per skill; directory name equals the skill name.

| Path | Required | Purpose |
|---|---|---|
| `SKILL.md` | yes | Front matter (`name`, `description`, optional `version`) + instruction body. |
| `references/` | no | Material read at runtime. |
| `scripts/` | no | Deterministic helpers. For a helper-backed skill this is the single implementation. |
| `assets/` | no | Static templates or inputs. |

### Release catalog metadata (generated at build)

```text
skills/
├── catalog.json          # generated manifest: skill names, versions, package hashes, catalog version
├── CHANGELOG.md          # human-readable Added/Changed/Deprecated/Removed
├── catalog-events.jsonl  # append-only release events
└── <skill-name>/ …
```

`catalog.json` is the tested-release manifest. It is generated from the packages, never hand-edited. Phase 4 introduces it and the change ledger; Phases 1 to 3 run with an implicit catalog version taken from the SPEED release.

### Projection (generated, disposable)

For Claude Code, `${PROJECT_ROOT}/.claude/skills/<skill-name>/` mirrors the canonical package with two differences: front matter is normalized to the surface's keys and SPEED provenance keys are injected (`x-speed-managed: true`, `x-speed-source: <name>`, `x-speed-catalog-version: <v>`); all other files (including `scripts/hello.py`) are copied byte-for-byte, so the projected helper hash equals the canonical helper hash. Projection is deterministic.

### Manifest (managed-file identity)

`${PROJECT_ROOT}/.speed/skills/manifest.json`. Records, per `(surface, skill)`: `projected_at_version`, optional skill `version`, and a `files` map of relpath to SHA-256. The recomputed on-disk hash versus the recorded hash is the only authority for distinguishing SPEED-managed bytes from user edits.

### Project install-event log

`${PROJECT_ROOT}/.speed/skills/events.jsonl`, append-only. Each `sync`/repair appends one event per `(surface, skill)` under a single transaction id: `{transaction, catalog_version, surface, skill, action, prev_version, new_version, ts}` where action is one of `installed`, `updated`, `unchanged`, `conflict`, `removed`, `failed`. It proves what changed on each surface and never contains prompts, generated content, or credentials.

## State Machine

Each `(surface, skill)` resolves to one state. Manifest hashes plus on-disk hashes drive it; nothing else does.

| State | Condition | Sync action | Event |
|---|---|---|---|
| `absent` | in catalog, no projection, no manifest entry | project | `installed` |
| `current` | on disk, hashes match manifest, catalog version matches | no write | `unchanged` |
| `stale` | catalog advanced; on-disk still matches old manifest | re-project | `updated` |
| `conflicted` | on-disk hash differs from manifest | preserve; require `--force` | `conflict` |
| `orphaned` | manifest+projection exist, skill gone from catalog | remove if unmodified else conflict | `removed` |
| `unsupported` | surface not detected | skip | none |

`conflicted → current` never happens silently; it requires `--force` or a manual delete. That is the whole point of managed-file identity.

## API Surface

### Command namespace

`workbench` is canonical. `speed` entries are temporary aliases that route to the identical implementation and are labeled as such in help and output.

| Canonical (`workbench`) | Temporary alias (`speed`) | Behavior |
|---|---|---|
| `workbench init` | `speed init` | Bootstrap project; projects the catalog into detected surfaces (non-fatal). |
| `workbench skills sync [--surface][--force][--json]` | `speed skills sync …` | Converge surfaces to the catalog; append install events. |
| `workbench skills status [--json]` | `speed skills status …` | Read-only per-surface state table. |
| `workbench skills doctor [--json]` | `speed skills doctor …` | Diagnose non-`current` states, one repair path each (Phase 2; aliases to status until then). |
| `workbench hello [name]` | `speed hello [name]` | Execute the canonical `scripts/hello.py`; surface = `workbench-cli`. |

Exit codes: `sync` 0 converged / 2 conflicts remain / 3 error; `status` 0 all current / 1 drift / 3 error; `hello` 0 ok / 3 error.

The alias policy: a `speed` command is retained only with an explicit `workbench` target, identical implementation/state/gates/provenance, and a temporary-alias label. New lifecycle behavior is authored under `workbench`; no independent `speed` workflow is added.

### Python engine (`lib/skills/`)

Invoked as `PYTHONPATH="${SPEED_DIR}/lib" <python> -m skills <sub> …` (because `lib/` is not a package; `lib/skills/` is).

| Module | Responsibility |
|---|---|
| `frontmatter.py` | parse/serialize SKILL.md front matter (stdlib) |
| `catalog.py` | discover/load canonical packages |
| `validate.py` | package + catalog contract (names, refs, paths, uniqueness) |
| `targets.py` | surface detection + destination |
| `project.py` | pure render to bytes with provenance injection |
| `manifest.py` | hashing, manifest I/O, state classification |
| `events.py` | append-only install-event log |
| `sync.py` | orchestrate detect → classify → apply → manifest + events (sole writer) |
| `__main__.py` | argparse CLI: `sync`, `status`, `hello` |

`hello` resolves the canonical `skills/workbench-hello/scripts/hello.py` and executes it, so the engine and every adapter reuse one implementation.

## Validation Rules

Run at catalog build and defensively at load. Each maps to a fixture in `tests/skills/`.

| Condition | Constraint | On violation |
|---|---|---|
| `SKILL.md` presence | required per skill | reject, name dir |
| `name` | `^[a-z0-9][a-z0-9-]*$`, equals dir name | reject |
| `description` | non-empty | reject |
| name uniqueness | unique across catalog | reject, name collision |
| relative refs | resolve inside package | reject, name path |
| path safety | no absolute, no `..`, no escaping symlink | reject, name path |
| helper-backed skill | CLI adapter carries no duplicate of the helper's logic | conformance test fails |
| idempotency | second render equals first | fail build |

## Testing

### Acceptance Criteria

- `workbench init` (and `speed init` alias) projects `workbench-hello` and `workbench-draft` into `.claude/skills/` with provenance front matter and every file present.
- `workbench hello Mohit` returns the greeting invariant, `catalog_version`, and `surface: workbench-cli`, executed by the canonical `scripts/hello.py`.
- Changing `scripts/hello.py` and syncing changes both the CLI and the projected-skill output with no edit to adapter code (shared-implementation proof).
- A stale projection whose helper hash differs from the canonical hash is not reported as equivalent.
- `workbench skills status` reports one row per detected surface with a State-Machine state.
- A second `sync` with an unchanged catalog writes nothing (manifest and projections untouched).
- Editing a projected file makes it `conflicted`; it is preserved unless `--force`.
- Each sync appends install events under one transaction id with the correct action per skill/surface.
- `speed hello` / `speed skills` / `speed init` produce identical results to their `workbench` canonical and print a temporary-alias notice.

### Risks and Coverage

| Risk | Severity | Test |
|---|---|---|
| CLI reimplements the greeting instead of reusing the helper | High | delete/alter helper → conformance fails; hash-equality of CLI and projection helper |
| Sync overwrites a user edit | High | edit-then-sync preserves bytes; `--force` overwrites |
| Non-deterministic render | High | `render(x)==render(x)`; golden snapshot |
| Orphan removal deletes a modified dir | High | modified orphan downgrades to conflict |
| Path traversal escapes project | High | `..`/absolute rejected by validate |
| Event log leaks sensitive data | Medium | events contain only names/versions/hashes/actions |

### Test Plan

- **Unit:** `frontmatter`, `catalog`, `validate` (rule table), `project` determinism + provenance, `manifest.classify` (six states), `targets`, `events` append shape, and `hello.py` input normalization/output.
- **Integration:** drive `lib.skills.__main__` end to end: init→sync→status; edit→conflict→force; version-bump→stale→update; remove→orphan→delete; interrupted-sync convergence; events.jsonl content.
- **Shared-implementation conformance:** CLI `hello` output and projected-skill helper come from the same `scripts/hello.py` (hash equality); mutating the helper changes both routes.
- **End-to-end:** `workbench`/`speed` bash routes against a fixture project asserting the `.claude/skills/` tree and status table. (Cannot run where the `speed_check_deps` grammar gate is unmet; verified via isolated function tests there.)
- **Compatibility/regression gate (Phase 4):** the SK-T01…SK-T13 matrix from the note (collision, full-catalog regression, upgrade/rollback, interruption, permission-expansion, log integrity). Design-complete here; implemented when the catalog carries versions and `catalog.json`.

### Out of Scope (this RFC's near phases)

- Full compatibility/regression harness SK-T01…T13 and impact graph (Phase 4).
- `catalog.json`, `CHANGELOG.md`, `catalog-events.jsonl` generation (Phase 4).
- Per-skill semantic versioning enforcement and migration contracts (Phase 4).
- Other module commands (`workbench discover|plan|audit|define`) (Phase 5).
- Per-skill enable/disable and per-skill model selection (never; product decision).

## Security & Controls

- No new permissions: a skill inherits the invoking surface's model, permissions, and approval controls. Installing grants nothing.
- No path escape: validation rejects absolute paths, `..`, and escaping symlinks.
- Bounded writes: sync writes only under detected surface roots, `.speed/skills/manifest.json`, and `.speed/skills/events.jsonl`. It never touches `.claude/settings.json`, existing `.claude/agents/`, or user skills it did not create.
- Generation is separate from approval; a skill run cannot ratify its own output.
- `workbench-hello` writes no artifact and touches no module state; the proof includes a no-write assertion.
- Helper honesty: a failing helper surfaces its failure; the agent must not fabricate the result.

## Key Decisions

| Decision | Choice | Alternatives | Rationale |
|---|---|---|---|
| First skill | `workbench-hello`, helper-backed | `workbench-draft` first | The note requires proving the platform (catalog→projection→routing→discovery→provenance→idempotency→repair) with a minimal helper-backed skill before any module skill. |
| Namespace | `workbench` canonical; `speed` temporary aliases | keep `speed skills` | The note mandates one platform namespace and a labeled, behaviorally identical alias for retained `speed` commands. |
| Shared implementation | one canonical `scripts/hello.py`; adapters are thin | CLI reimplements greeting | Proves a command and an agent skill reuse one implementation; establishes the pattern for every later module command. |
| Engine | SPEED-native lean Python in `lib/skills/` | vendor Forge `forge_sync` | Forge carries surfaces/CI/aliases SPEED does not need; a small owned package fits SPEED's `lib/*.py` style. |
| First surface | Claude Code; Codex additive via `targets.py` | both at once | One adapter proves the contract and unlocks direct invocation immediately. |
| Managed identity | per-file SHA-256 + provenance keys | provenance marker only; diff-vs-source | Hashing is the only reliable edit detector across interrupted sync and manual deletion. Injected front matter means diff-vs-source is invalid; the manifest hash is authoritative. |
| Install events | `.speed/skills/events.jsonl` under a transaction id | none | Satisfies SK-S10 and lets interrupted multi-surface sync resume without repeating successes. |

## Drawbacks

- A `workbench` binary plus `speed` aliases is a second entrypoint to maintain until `speed` retirement. Mitigation: aliases forward to one implementation; no second workflow exists.
- Shipping `workbench-hello` adds a permanent smoke-test package. That is intentional; it is the release conformance fixture.
- The full compatibility gate (SK-T01…T13) and versioned catalog are large and deferred to Phase 4; until then catalog version tracks the SPEED release and cross-skill regression is limited to the shipped tests. Status/doctor report honestly in the interim.
- Provenance keys make the projected `SKILL.md` non-identical to source, so only the manifest hash is a valid conflict check (a naive diff would be wrong).

## Migration Strategy

Additive; no existing skill data to migrate. Re-phased to match the note's bootstrap order:

| Phase | Delivers | Unlocks |
|---|---|---|
| 1 | catalog format, engine (validate/render/manifest/events), `workbench skills sync`/`status`, `workbench init` hook, `workbench-hello` + shared helper, `workbench hello`, `speed` aliases | platform proof: CLI + agent run one implementation |
| 2 | `doctor` with one-repair-path, conflict/orphan/rename hardening, `workbench-draft` module skill + guided-authoring hook | module skills on the proven platform |
| 3 | Codex `.agents/skills/` adapter | cross-surface parity |
| 4 | `catalog.json`, change ledger, per-skill versioning, SK-T01…T13 compatibility gate | safe platform evolution |
| 5 | other module commands (`workbench discover`, `plan`, `audit`, `define`) | full Workbench namespace |

Rollback: catalog version tracks the SPEED release, so downgrading SPEED and syncing re-projects the prior catalog; unmodified projections update down, conflicts are preserved. `init` calling `sync` is non-fatal, so a projection failure or missing surface cannot break setup.

## File Impact

New:
- `skills/workbench-hello/{SKILL.md,scripts/hello.py}`: platform proof package.
- `skills/workbench-draft/SKILL.md`: module skill (Phase 2 body from guided authoring).
- `lib/skills/{__init__,__main__,frontmatter,catalog,validate,targets,project,manifest,events,sync}.py`: engine.
- `lib/cmd/skills.sh`, `lib/cmd/hello.sh`: bash wrappers.
- `workbench`: canonical dispatcher (forwards to the shared implementation).
- `tests/skills/…`: fixtures + suites.

Modified:
- `speed`: `skills)`/`hello)` cases as temporary aliases with a notice.
- `lib/cmd/project.sh`: `cmd_init` projection step (non-fatal); gitignore `.speed/skills/`.

Not touched: `.claude/settings.json`, existing `.claude/agents/`, `speed.toml` (no `[skills]` section), user-authored skills.

## Dependencies

- Python 3.11 project `.venv`, stdlib only (`hashlib`, `json`, `pathlib`, `argparse`, `uuid`, `dataclasses`). No `requirements.txt` change.
- SPEED release version for `catalog_version`.
- `workbench-draft` interview contract and question banks from [03-guided-authoring.md](../product/define-module/03-guided-authoring.md) (Phase 2).

## Unresolved Questions

| Question | Blocks | Proposed path |
|---|---|---|
| Should `workbench` be a standalone binary or a mode of `speed`? | namespace shape | Phase 1 ships a thin `workbench` forwarder; revisit a full split when `speed` retirement is scheduled. |
| Transaction-id source without wall-clock nondeterminism in tests | event-log tests | Use `uuid4` for the id and a passed/late-stamped timestamp; assert structure, not exact time. |
| Where does cross-module workflow provenance live? | SK-S9/Phase 4 | reuse the module's existing `.speed/` feature record; confirm with the orchestration owner. |
| `catalog.json` generation: build step vs first-load | Phase 4 | generate at release build; load-time only validates. |
