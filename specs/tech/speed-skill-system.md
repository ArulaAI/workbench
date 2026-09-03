# RFC: Workbench Skill System

This RFC specifies the technical design for the Workbench Skill System: a canonical skill catalog, a lean Python projection engine, managed-file identity, the `workbench` command namespace with temporary `speed` aliases, and `workbench-health` as the sole platform proof skill.

Scope here is packaging, validation, harness projection, routing, health verification, diagnostics, and lifecycle. Module workflow skills are intentionally excluded and belong on separate feature branches after this platform foundation is accepted.

## Scope Boundary

This branch proves only the reusable skill-system architecture and its installation contract:

- `workbench-health` is the only canonical package shipped by this RFC.
- `workbench` is the canonical command namespace; retained `speed` commands are labeled temporary aliases.
- Harness selection, projection, managed identity, health verification, doctor diagnostics, and lifecycle behavior are platform services.
- Domain and module workflow skills are out of scope for this branch.

## Basic Example

The platform proof skill is intentionally small and useful. It is helper-backed: one canonical `scripts/health.py` is the read-only implementation executed by the projected agent skill. It validates the project manifest and the hashes of every recorded projected skill file.

```text
skills/workbench-health/
├── SKILL.md          # invocation + read-only readiness contract
└── scripts/
    └── health.py     # the ONE health-check implementation (stdlib)
```

The platform flow projects the canonical package, invokes it through the agent harness, and reports the same managed state through lifecycle commands:

```console
$ workbench init --harness codex
✓ Skills projected for codex

> /workbench-health
skill: workbench-health
status: healthy
message: Workbench skills were imported successfully and are ready to use.
catalog_version: 0.1.0
harness: codex
skills: workbench-health

$ workbench skills status
catalog 0.1.0 · 1 skill
  codex        workbench-health  current
```

The selected harness invokes `/workbench-health`; the projected `SKILL.md` runs `scripts/health.py` against the current project. `speed init` and `speed skills …` remain as temporary aliases that route to the identical implementation and print a one-line notice naming the canonical `workbench` command. There is intentionally no `workbench health` or `speed health` command; health is an agent skill only.

## Data Model

Four artifacts: the canonical package, the projection, the manifest, and the append-only logs.

### Canonical package (source of truth)

Lives at `${SPEED_DIR}/skills/<skill-name>/`. One directory per skill; directory name equals the skill name.

| Path | Required | Purpose |
|---|---|---|
| `SKILL.md` | yes | Front matter (`name` and `description`) + instruction body. Per-skill version metadata is deferred to Phase 4. |
| `references/` | no | Material read at runtime. |
| `scripts/` | no | Deterministic helpers. For a helper-backed skill this is the single implementation. |
| `assets/` | no | Static templates or inputs. |

### Projection (generated, disposable)

Workbench supports three project harness targets:

| Harness | Projection root | Marker |
|---|---|---|
| `claude` | `.claude/skills/` | `.claude` |
| `codex` | `.agents/skills/` | `.agents` |
| `copilot` | `.github/skills/` | `.github/skills` |

A harness has one name and one identifier, and they are the same string. An
earlier revision carried a separate surface id (`claude_code`) alongside the
harness name (`claude`), which put two vocabularies in the manifest, the JSON
output, the diagnostics, and two different CLI flags for one concept that never
behaved differently. The registry is `HARNESSES` in `skills/models.py` and is
the only place the list exists: the Bash commands query it through
`python -m skills harnesses` rather than restating it.

[GitHub documents](https://docs.github.com/en/copilot/concepts/agents/about-agent-skills) `.github/skills`, `.agents/skills`, and `.claude/skills` as supported Copilot project skill locations; Workbench uses `.github/skills` as the harness-specific Copilot target. Each projection mirrors the canonical package with two differences: front matter is normalized to the harness's keys and Workbench provenance keys are injected (`x-workbench-managed: true`, `x-workbench-source: <name>`). The projecting install is recorded in `manifest.json`, not in the projected file, so that a committed projection is byte-identical for every teammate regardless of which SPEED build ran the sync. All other files, including `scripts/health.py`, are copied byte-for-byte, so the projected helper hash equals the canonical helper hash. Projection is deterministic.

Execution provider and skill harness are independent. `[agent].provider` selects the backend that runs Workbench agents; `[skills].harnesses` selects the project roots that host skills. A Claude provider with a Codex skill harness is therefore valid, as is a project that hosts skills in several harnesses.

`[skills].harnesses` in `speed.toml` is the durable source of project intent. Initialization resolves policy in this order: repeated `--harness` flags, `WORKBENCH_HARNESSES`, `[skills].harnesses`, the legacy manifest selection for migration, then existing harness markers. The resolved initialization policy is persisted to `speed.toml`; the legacy manifest field is removed. A later bare `sync` therefore cannot forget the init choice or fan out because a new marker appeared. If no level yields a harness, init exits 3 before writing and asks for `workbench init --harness <name>`. Copilot detection requires `.github/skills/`; a generic `.github/` directory alone does not imply Copilot usage.

### Manifest (managed-file identity)

`${PROJECT_ROOT}/.speed/skills/manifest.json`. Records, under `harnesses.<harness>.skills.<skill>`: `projected_at_version`, optional skill `version`, and a `files` map of relpath to SHA-256. The recomputed on-disk hash versus the recorded hash is the only authority for distinguishing Workbench-managed bytes from user edits. The manifest records observed installation state, not desired harness policy. It is git-tracked alongside the projections it describes: a clone that carries the projected files without their recorded hashes has no way to tell them apart from a user edit and classifies every one as `conflicted`.

The state layout is defined once, as `SkillPaths` in `skills/__init__.py`: `state_root` is `.speed/skills`, with `manifest.json` and `events.jsonl` derived from it. Every module that touches those files reads the path from there. The projected health helper is the one exception, because it runs as a copy with no package to import from, so it carries its own literals and a test asserts they still agree with the canonical layout. Init reconciles a versioned Git-policy block on every run rather than treating the historical `# SPEED runtime state` header as proof that current rules exist. The later policy explicitly re-includes `.speed/skills/manifest.json` and ignores `.speed/skills/events.jsonl`, migrating both released projects with no skill rules and early projects that ignored `.speed/skills/` wholesale.

### Project install-event log

`${PROJECT_ROOT}/.speed/skills/events.jsonl`, append-only. Each `sync`/repair appends one event for every changed or conflicted `(harness, skill)` under a single transaction id: `{transaction, catalog_version, harness, skill, action, prev_version, new_version, ts}` where action is one of `installed`, `updated`, `conflict`, or `removed`. Current entries produce no event. The log proves what changed on each harness and never contains prompts, generated content, or credentials.

## State Machine

Each `(harness, skill)` resolves to one state. Manifest hashes plus on-disk hashes drive it; nothing else does. The states are a closed set, `SkillState` in `skills/models.py`, string-backed so they cross JSON unchanged while an unknown value cannot be constructed.

| State | Condition | Sync action | Event |
|---|---|---|---|
| `absent` | in catalog, no projection, no manifest entry | project | `installed` |
| `current` | on disk, hashes match manifest and match the rendered catalog | no write | none |
| `stale` | catalog advanced; on-disk still matches old manifest | re-project | `updated` |
| `conflicted` | on-disk hash differs from manifest | preserve; require `--force` | `conflict` |
| `orphaned` | manifest+projection exist, skill gone from catalog | remove if unmodified else conflict | `removed` |
| `unsupported` | no supported harness detected and none explicitly selected | skip | none |

`conflicted → current` never happens silently; it requires `--force` or a manual delete. That is the whole point of managed-file identity.

`current` is decided by content alone. `projected_at_version` is recorded for provenance and is deliberately not part of the comparison: it names the install that ran the sync, so comparing it would flag every skill `stale` for any teammate whose Workbench build differs from whoever synced last, churning `manifest.json` while not one projected byte changed. A catalog edit or a skill version bump changes `SKILL.md` itself, so content already catches every real update.

## API Surface

### Command namespace

`workbench` is canonical. `speed` entries are temporary aliases that route to the identical implementation and are labeled as such in help and output.

| Canonical (`workbench`) | Temporary alias (`speed`) | Behavior |
|---|---|---|
| `workbench init [--harness <claude\|codex\|copilot>]... [--commit]` | `speed init …` | Resolve and persist project harness policy, scaffold the project, project skills, verify convergence, apply Git policy, and optionally commit only Workbench-owned files. Missing policy, invalid configuration/catalog, conflicts, sync errors, and failed verification stop the lifecycle before commit. |
| `workbench skills sync [--harness][--force][--json]` | `speed skills sync …` | Converge harnesses to the catalog; append install events. |
| `workbench skills status [--harness][--json]` | `speed skills status …` | Read-only per-harness state table. `--harness` narrows the table the same way it narrows `doctor`, which reads the identical inspection. |
| `workbench skills doctor [--harness][--json]` | `speed skills doctor …` | Read-only diagnosis of every non-`current` finding, each with a stable code, its evidence, and exactly one repair path. |

Sync rows are `SyncOutcome` records reporting `previous_state`, `action`, and `final_state`, so a forced repair reports `conflicted` → `updated` → `current` rather than the classification it started from. `status` rows report `state` only, since nothing ran. Exit codes: `sync` 0 converged / 2 conflicts remain after the run / 3 error; `status` 0 all current / 1 drift / 3 error; `doctor` 0 no findings / 1 findings present / 3 error.

Usage and configuration errors exit 3 on every subcommand, never 1 or 2. A missing subcommand, an unknown subcommand, an unsupported option, and an argparse parse failure all land there, so 1 keeps meaning drift and 2 keeps meaning conflicts. `workbench skills` without a subcommand prints usage and exits 3; `workbench skills --help` prints the same usage and exits 0. The public wrapper accepts only `--harness`, `--force`, `--json`, and `--help`, so a caller cannot redirect the resolved project root or canonical catalog through the argument tail.

Errors carry detail rather than a bare line. `WORKBENCH_DEBUG=1` prints a traceback, `--json` emits `{"status": "error", "error": {"type", "message"}}` on stdout, and the one-line message stays on stderr for the shell callers that read it.

`workbench skills` is the only supported entrance to the engine. `python -m skills` is private plumbing: its `--project-root`, `--skills-dir` and `--catalog-version` arguments are context the wrapper resolves and passes in, which is why they are required and have no defaults, and the wrapper's option whitelist is what keeps them out of a caller's reach. The one subcommand that carries no project context is `harnesses`, which exists so the Bash commands can query the canonical harness registry instead of restating it. Its JSON form returns each harness id, projection root, and marker; the init commit phase derives its pathspecs from those records rather than carrying a Bash copy of the harness-to-root map.

Catalog version resolution distinguishes the three cases that once all reported `dev`: a `.git` directory in the install is a development checkout and reports `dev`, a receipt naming a version reports that version, and a missing or unparseable receipt is a broken managed installation that exits 3.

### Initialization ownership and ordering

`lib/skills/bootstrap.py` owns skill-bootstrap inspection, policy resolution, policy persistence, legacy migration, and post-sync verification. `cmd_init` is the single project-level coordinator and invokes the phases in this order:

1. Inspect existing configuration, manifest state, and harness markers; validate the canonical catalog.
2. Resolve the harness policy without writing.
3. Acquire the project mutation lock and create or preserve the general project scaffold.
4. Persist `[skills].harnesses` and retire legacy manifest intent.
5. Project the catalog into exactly the resolved harnesses.
6. Verify every selected projection is `current`.
7. Apply the Git tracking policy.
8. When `--commit` is present, stage only Workbench-owned paths and commit after convergence.

Fresh init, repeated init, post-clone setup, and upgrades use the same reconciliation path. Repeated init preserves runtime and user-owned files. Post-clone init reads the committed policy and manifest. Catalog upgrades flow through `skills sync` under that same policy. `--harness` on a lifecycle command is an operational scope; only initialization persists a changed project policy.

The bootstrap plan exposes only values the coordinator consumes: resolved harnesses, their source, and whether persistence or legacy migration is required. Malformed `speed.toml` is a configuration error at process startup and produces one error message; commands do not continue with defaults or run a second parser that reports the same failure again.

The alias policy: a `speed` command is retained only with an explicit `workbench` target, identical implementation/state/gates/provenance, and a temporary-alias label. New lifecycle behavior is authored under `workbench`; no independent `speed` workflow is added.

### Python engine (`lib/skills/`)

Invoked as `PYTHONPATH="${SPEED_DIR}/lib" <python> -m skills <sub> …` (because `lib/` is not a package; `lib/skills/` is).

| Module | Responsibility |
|---|---|
| `frontmatter.py` | load SKILL.md front matter as YAML (PyYAML) and inject provenance in place |
| `catalog.py` | discover canonical packages and reject catalog validation failures at load |
| `validate.py` | package + catalog contract (names, metadata, paths, symlinks, uniqueness) |
| `targets.py` | marker detection, harness lookup, and bounded destinations |
| `project.py` | pure render to bytes with provenance injection |
| `manifest.py` | hashing, manifest I/O, and classification with evidence |
| `events.py` | append-only install-event log |
| `bootstrap.py` | initialization inspection, harness-policy precedence and persistence, legacy migration, and verification |
| `models.py` | shared vocabulary: `SkillState`, `Harness`, `SkillPackage`, `Finding`, `Inspection`, `SkillPlan`, `SyncOutcome`, and the harness registry |
| `__init__.py` | `SkillPaths`, the legal skill-name rule, junk exclusions, and re-exported vocabulary |
| `inspect.py` | read-only: assemble the whole picture as an `Inspection` (no writes) |
| `sync.py` | `plan(Inspection, force) → [SkillPlan]`, then `apply(...) → [SyncOutcome]` (sole writer) |
| `doctor.py` | read-only: `diagnose(Inspection) → [Diagnostic]` against a catalog keyed by code |
| `__main__.py` | argparse CLI: `sync`, `status`, `doctor`, `harnesses` |

Reading is separated from writing, not by convention but by dependency: `inspect.py` and `doctor.py` do not import `sync.py`, so a read-only command cannot reach the write path even by mistake. Every module depends on `models.py` and, apart from the loader's use of the validator, not on each other. `status` and `doctor` consume one `Inspection`; only `sync` turns one into operations, and it does that in two steps so the plan can be examined before anything is written. The arrangement this replaced had `doctor` importing `status` from the writer, which meant a read-only command built a set of filesystem mutations and discarded them.

The projected `workbench-health` skill executes its packaged `scripts/health.py` directly. The helper reads `.speed/skills/manifest.json`, verifies that the selected harness has installed skills, and checks each projected file against its recorded SHA-256. It performs no writes and has no Workbench CLI adapter.

`doctor` consumes the same `Inspection` as `status` and reports only non-`current` findings. A state says what sync will do; a diagnostic says what is wrong, so the two are kept apart. States stay a small closed set while the explanations live in a catalog keyed by stable code, and each definition owns its severity, wording, repair command, and whether that repair can destroy work:

| Code | State | Severity | Repair |
|---|---|---|---|
| `projection_missing` | `absent` | warning | `workbench skills sync` |
| `projection_outdated` | `stale` | warning | `workbench skills sync` |
| `projected_file_modified` | `conflicted` | error | `sync --harness <harness> --force` (destructive) |
| `projected_file_missing` | `conflicted` | error | as above |
| `projected_file_unexpected` | `conflicted` | error | as above |
| `projection_path_occupied` | `conflicted` | error | as above |
| `projection_symlink` | `conflicted` | error | as above |
| `manifest_record_missing` | `conflicted` | error | as above |
| `orphaned_projection` | `orphaned` | warning | `workbench skills sync` |
| `orphaned_record` | `orphaned` | warning | `workbench skills sync` |
| `orphaned_projection_modified` | `conflicted` | error | `sync --harness <harness> --force` (destructive) |
| `manifest_lost` | project-level | error | restore `manifest.json` from version control |
| `harness_unsupported` | `unsupported` | note | `workbench init --harness <claude\|codex\|copilot>` |
| `internal_unknown_state` | any | error | report it: the classifier and the catalog disagree |

`conflicted` alone covers six of those, which is why one prose line per state was not enough to act on. Each diagnostic carries `path`, `expected`, and `actual` taken from the inspection, so the output shows the hash comparison the classification was made from instead of asserting its conclusion, and one skill can report several findings at once. Every code the engine can emit is checked against the catalog at import, so a missing definition is a startup failure the author sees rather than a bare code the user reads. `destructive` is explicit for callers that need to confirm before running a repair.

Only the destructive repair is scoped. `--harness` is the narrowest scope sync accepts, so a harness carrying two conflicts still repairs both; per-skill scoping would require a new flag. The non-destructive repairs stay project-wide because nothing they do can lose work. One case is reported for the project rather than per skill: when projections exist but `.speed/skills/manifest.json` does not, every skill would otherwise classify as `conflicted` and be blamed on a local edit, when the files are untouched and the record of them is what went missing. A healthy result contains no diagnostics. Text and JSON outputs carry the same fields.

## Validation Rules

Run whenever the canonical catalog is loaded; a future release build can reuse the same validator. Each rule maps to a fixture in `tests/skills/`.

| Condition | Constraint | On violation |
|---|---|---|
| `SKILL.md` presence | required per skill | reject, name dir |
| `name` | `^[a-z0-9][a-z0-9-]*$`, equals dir name | reject |
| `description` | non-empty | reject |
| `name`, `description`, `version` types | must be YAML strings; quote a value that would load as a bool, number or null | reject, name field and type |
| front-matter shape | block holds a mapping with string keys, no repeated key | reject |
| name uniqueness | unique across catalog | reject, name collision |
| path safety | no absolute, no `..`, no symlink of any kind | reject, name path |
| reserved keys | no author-declared `x-workbench-*` front matter | reject, name key |
| helper-backed skill | projected helper is byte-identical to canonical helper | conformance test fails |
| idempotency | second render equals first | fail test/release gate |

## Testing

### Acceptance Criteria

- `workbench init` (and `speed init` alias) projects only `workbench-health` into every detected supported harness with provenance front matter and every file present.
- `workbench init --harness <value>` accepts exactly `claude`, `codex`, or `copilot`, creates the selected harness root when absent, persists it under `[skills].harnesses`, and projects the health-only catalog into that root.
- Repeated `--harness` flags persist and initialize multiple harnesses. Without the flag, environment, project configuration, legacy migration, and existing markers are checked in documented precedence order.
- A fresh project with no resolvable harness policy exits 3 before creating a Git repository or scaffold.
- `[agent].provider` and `[skills].harnesses` may name different products without either overriding the other.
- Repeated and post-clone init use the persisted project policy and do not fan out when a new harness marker appears.
- Init commits only with `--commit`, only after verification, and never stages unrelated project files.
- A manifest that records no skills, including an empty `{}` document, is reported `unhealthy`.
- Direct `workbench-health` skill invocation reports `healthy` and the readiness message only when the manifest exists, at least one skill is recorded for the selected harness, and every recorded projected file exists with its expected hash.
- Removing or modifying a projected file makes direct `workbench-health` invocation report `unhealthy`, list the affected skill/file, and exit nonzero.
- Changing canonical `scripts/health.py` and syncing changes the projected-skill behavior without a CLI adapter.
- A stale projection whose helper hash differs from the canonical hash is not reported as equivalent.
- `workbench skills status` reports one row per detected harness with a State-Machine state.
- `workbench skills doctor` is read-only, exits 0 when every projection is current, and exits 1 with exactly one diagnosis and repair path for each non-current row.
- Doctor text and JSON results cover `absent`, `stale`, `conflicted`, `orphaned`, and `unsupported` states without changing projected files or the manifest.
- A second `sync` with an unchanged catalog writes nothing (manifest and projections untouched).
- Editing a projected file makes it `conflicted`; it is preserved unless `--force`.
- Each sync appends install events under one transaction id for changed or conflicted skills and appends nothing for current skills.
- `speed skills` / `speed init` produce identical results to their `workbench` canonical and print a temporary-alias notice.

### Risks and Coverage

| Risk | Severity | Test |
|---|---|---|
| Projected skill fabricates readiness instead of running its helper | High | helper failure must surface; canonical/projected helper hash equality |
| Sync overwrites a user edit | High | edit-then-sync preserves bytes; `--force` overwrites |
| Non-deterministic render | High | `render(x)==render(x)`; golden snapshot |
| Orphan removal deletes a modified dir | High | modified orphan downgrades to conflict |
| Path traversal escapes project | High | `..`/absolute rejected by validate |
| Event log leaks sensitive data | Medium | events contain only names/versions/hashes/actions |
| Doctor recommends an unsafe or ambiguous repair | High | state-to-guidance unit matrix; conflict guidance requires review/backup before `--force`; read-only assertion |
| Explicit init leaks skills into unselected harnesses | High | parameterized shell E2E for all harnesses plus multi-target absence assertions |

### Test Plan

- **Unit:** `frontmatter`, `catalog`, `validate` (rule table), `project` determinism + provenance, `manifest.classify` (six states), `doctor` state-to-repair mapping, harness target resolution/detection, `events` append shape, and `health.py` healthy/missing/modified projection results.
- **Integration:** drive `lib.skills.__main__` end to end: init→sync→status→doctor; edit→conflict diagnosis→force; version-bump→stale diagnosis→update; remove→orphan diagnosis→delete; unsupported-harness diagnosis; events.jsonl content.
- **Projection conformance:** canonical and projected `scripts/health.py` are byte-identical; mutating the canonical helper and syncing changes direct skill behavior.
- **End-to-end:** `workbench init --harness` against fresh fixture projects for Claude, Codex, and Copilot, asserting root creation, the health-only projection, and absence of unselected projections; `workbench`/`speed` status and doctor routes plus direct projected health-skill execution run against fixtures.

### Out of Scope

- Full compatibility/regression harness SK-T01…T13 and impact graph (Phase 4).
- `catalog.json`, `CHANGELOG.md`, `catalog-events.jsonl` generation (Phase 4).
- Per-skill semantic versioning enforcement and migration contracts (Phase 4).
- All domain and module workflow skills and their commands.
- Per-skill enable/disable and per-skill model selection (never; product decision).

## Security & Controls

- No new permissions: a skill inherits the invoking harness's model, permissions, and approval controls. Installing grants nothing.
- No path escape: validation rejects absolute paths and `..`. Packages prohibit symlinks outright rather than only escaping ones, because projection copies bytes and never preserves a link, so no supported use case needs them. Refusal happens at read time, before any linked target is opened, which makes validation the actual boundary instead of a check run after unsafe content is already in memory.
- No read-through: harness markers, projection roots, and projected files are all walked without following links. A symlink where a managed file belongs is reported as `conflicted`, never hashed through.
- Durable state: the manifest is written to a staging file in the same directory and swapped in with `os.replace`, so an interrupted run cannot truncate the one record that distinguishes a managed byte from a user edit. A projection is staged in full and swapped into place, so a failed write leaves the previous projection intact rather than a half-installed skill.
- Fail closed on catalog load: a missing or unreadable catalog directory is an installation error (exit 3), never an empty catalog. Sync plans no removals when the catalog cannot be read.
- Bounded writes: sync writes only under detected or explicitly selected harness roots, `.speed/skills/manifest.json`, and `.speed/skills/events.jsonl`. It never touches harness settings, agent definitions, or user skills it did not create.
- Generation is separate from approval; a skill run cannot ratify its own output.
- `workbench-health` writes no artifact and touches no module state; the proof includes a no-write assertion.
- Helper honesty: a failing helper surfaces its failure; the agent must not fabricate the result.

## Key Decisions

| Decision | Choice | Alternatives | Rationale |
|---|---|---|---|
| Proof package | `workbench-health`, helper-backed, and the only shipped skill | ship a module workflow concurrently | A health check isolates and proves catalog→projection→routing→discovery→provenance→idempotency→repair before downstream skills are introduced. |
| Namespace | `workbench` canonical; `speed` temporary aliases | keep `speed skills` | The note mandates one platform namespace and a labeled, behaviorally identical alias for retained `speed` commands. |
| Health invocation | agent skill only; projected `scripts/health.py` is the implementation | add `workbench health` / `speed health` commands | Keeps readiness in the installed skill harness while `workbench skills doctor` owns CLI diagnostics. |
| Engine | SPEED-native lean Python in `lib/skills/` | vendor Forge `forge_sync` | Forge carries harness/CI/alias machinery SPEED does not need; a small owned package fits SPEED's `lib/*.py` style. |
| Harness policy | `[skills].harnesses`; CLI > environment > config > legacy manifest > detection | derive from `[agent].provider`; keep manifest-only intent | Provider and skill host are separate business concepts, while durable project configuration prevents init and later sync from selecting different targets. |
| Managed identity | per-file SHA-256 + provenance keys | provenance marker only; diff-vs-source | Hashing is the only reliable edit detector across interrupted sync and manual deletion. Injected front matter means diff-vs-source is invalid; the manifest hash is authoritative. |
| Install events | `.speed/skills/events.jsonl` under a transaction id | none | Provides an auditable record of projection mutations and conflicts without logging prompts or generated content. |

## Drawbacks

- A `workbench` binary plus `speed` aliases is a second entrypoint to maintain until `speed` retirement. Mitigation: aliases forward to one implementation; no second workflow exists.
- Shipping `workbench-health` adds a permanent read-only diagnostic package. It is both a user-facing readiness check and the release conformance fixture.
- The full compatibility gate (SK-T01…T13) and versioned catalog are deferred; until then catalog version tracks the SPEED release and regression coverage is limited to the health-only catalog and engine tests. Status and doctor report this state honestly.
- Provenance keys make the projected `SKILL.md` non-identical to source, so only the manifest hash is a valid conflict check (a naive diff would be wrong).

## Delivery and Cleanup

This branch delivers the catalog format, engine, Claude/Codex/Copilot harness targets, selective `workbench init --harness`, `workbench skills sync|status|doctor`, and agent-only `workbench-health`. Downstream workflow skills must be introduced on separate branches with their own contracts and tests.

If a project manifest contains a managed skill that is no longer in this health-only catalog, normal orphan handling applies: sync removes an unmodified projection and preserves a modified projection as a conflict. Downgrading and syncing re-projects the prior catalog; conflicts are never overwritten silently. Init succeeds only after the selected projections verify as current; a conflict exits 2 and an operational or verification failure exits 3 without creating an initialization commit.

## File Impact

New:
- `skills/workbench-health/{SKILL.md,scripts/health.py}`: platform readiness package.
- `lib/skills/{__init__,__main__,bootstrap,frontmatter,catalog,validate,targets,project,manifest,events,sync,doctor}.py`: engine, bootstrap coordinator, and read-only diagnostics.
- `lib/cmd/skills.sh`: bash wrapper for skill lifecycle and doctor commands.
- `workbench`: canonical dispatcher (forwards to the shared implementation).
- `tests/skills/…`: fixtures + suites.

Modified:
- `speed`: `skills)` case as a temporary alias with a notice.
- `lib/cmd/project.sh`: ordered init phases, repeatable `--harness`, verification gate, explicit Git policy, and scoped `--commit` behavior.
- `install.sh`: links `workbench` into `~/.speed/bin` alongside the `speed` alias.
- `lib/cmd/skills.sh`: applies CLI, environment, and project-config harness precedence and forwards multiple resolved harnesses.
- `lib/toml.py` + `templates/speed-toml.toml`: `[skills].harnesses` project configuration.
- `requirements-dev.txt` + README `## Tests`: declared pytest dependency and the canonical `PYTHONPATH=lib python3 -m pytest tests/skills/` command.
- `lib/cmd/mp_init.sh`: the multi-player allowlist un-ignores `skills/manifest.json` and keeps `skills/events.jsonl` local.

Not touched: harness settings, existing agent definitions, `[agent].provider`, user-authored skills, and unselected harness skill roots.

## Dependencies

- Python 3.11 project `.venv`. The engine is stdlib (`hashlib`, `json`, `pathlib`, `argparse`, `uuid`, `dataclasses`) plus `PyYAML>=6.0,<7.0`, declared in `requirements.txt`.
- Front matter is YAML, so it is read by a YAML implementation rather than approximated. A partial parser misreads the inputs a partial parser misreads: a quoted `name` keeps its quotes and is reported as disagreeing with its own directory, a `#` comment becomes a key, and every scalar arrives as a string. `parse` runs `yaml.safe_load` and then enforces two rules on top: the block must hold a mapping with string keys, and a repeated key is an error rather than a last-one-wins.
- `inject` still edits the block in place and does not round-trip through `safe_dump`, because re-emitting a parsed document reorders keys, drops comments, and rewrites an author's quoting and block scalars, all of which would appear as a diff in a committed projection. The values Workbench writes are serialized by `safe_dump`, so `managed` is the boolean `true` while a skill named `true` or `on` is quoted.
- `scripts/health.py` stays stdlib-only. It is projected into a harness directory and executed there with no package around it, so it can import nothing, PyYAML included.
- SPEED release version for `catalog_version`.

## Unresolved Questions

| Question | Blocks | Proposed path |
|---|---|---|
| Should `workbench` be a standalone binary or a mode of `speed`? | namespace shape | Phase 1 ships a thin `workbench` forwarder; revisit a full split when `speed` retirement is scheduled. |
| `catalog.json` generation: build step vs first-load | Phase 4 | generate at release build; load-time only validates. |
