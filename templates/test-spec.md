# Test Spec: {Feature Name}

> See [{tech-spec}]({tech-spec}) for the technical contract under evaluation.
<!-- The first "> See [...]" link must point to the RFC whose acceptance
     criteria this evaluation spec covers. Add PRD or sibling RFC references
     as additional blockquote lines when useful. -->

## Sources and Review
<!-- Identify the exact source versions this spec evaluates. Use a commit SHA,
     published snapshot ID, or document revision; a moving branch alone is not
     a baseline. Link relevant PRD and Design requirements when applicable.
     After a source changes, review affected scenarios, mappings, and expected
     outcomes before claiming coverage for the new version. -->

| Source | Version / revision | Requirements or sections used |
|---|---|---|
| [{tech-spec}]({tech-spec}) | | |

- **Spec owner:**
- **Review status:** Draft / In review / Reviewed
- **Reviewer and review date:**
<!-- Remove unused status choices. Review of this spec is not evidence that
     the implementation passes. Keep run results in the execution report. -->

## Scope
<!-- State which RFC and user stories this evaluation spec covers and how the
     scenario catalog is organized. Identify the affected behavior and existing
     behavior that must remain unchanged. List assumptions and unresolved
     decisions with the scenarios they block; do not invent product behavior,
     thresholds, error contracts, or ownership to complete a test case. -->

## Test Levels
<!-- Keep only the levels used by scenarios and delete the rest. Add
     project-specific levels when needed. Every Scenario Catalog level must
     match a row in this table. Fill in Tooling and Environment with what the
     project actually uses, including which dependencies are real or replaced.
     The base command belongs in `speed.toml` under `[eval]` as
     `test_command`, or in the project agent file as `test: <command>` under
     `## Quality Gates`, optionally within `### Frontend` or `### Backend`.
     Reference that configuration here instead of maintaining a second command. -->

| Level | Meaning | Tooling | Environment |
|---|---|---|---|
| unit | One component or module, with controlled dependencies where needed | | Local process |
| integration | Interactions between components, services, or storage | | Required services or test dependencies |
| e2e | Full request or user path through the running application | | Application and dependencies |

<!-- Classify new scenarios by their test level above and their category in
     Scenario Classification below. Security and performance are categories,
     not levels; either can be checked at more than one level. Existing specs
     may retain execution labels such as contract, db, ui, performance, or
     security: define those labels in this table if they remain in use, and
     do not silently change existing scenario identities or runner mappings. -->

## Entry Conditions
<!-- State what must be ready to execute each selected level. These conditions
     establish a runnable environment, not a requirement for unfinished feature
     behavior to pass before a test can run. -->

- **Build and configuration:** Tested application revision, feature flags, and relevant runtime versions.
- **Services and storage:** Required dependencies, health checks, schema/migration state, and supported configuration variants.
- **Access and data:** Test accounts and roles, configured credentials, and loaded fixtures. Reference secret names, never secret values.
- **Blocking dependencies:** Unavailable environments, source decisions, or prerequisites, and the scenarios they prevent from running.

## Scenario Catalog
<!-- Group scenarios by functional concern, one H3 area per concern. Never
     group by whether a test exists yet; a scenario the specs require belongs
     in its area even before it has a test, and the empty Selector cell in the
     Execution and Evidence table is what records that gap. Replace the
     example rows below; they are there to show the format.

     IDs are PREFIX-NN, unique across the file and stable once assigned,
     because traceability rows and generated tests reference them.
     Conventional prefixes: AC- acceptance, RISK- high risk, VAL- validation,
     EDGE- edge case.

     Expected outcome must be observable at the selected level. Include exact
     returned values and relevant persisted state, side effects, and invariants.
     A successful response alone does not prove persistence or idempotency.
     For rejected operations, verify that no partial change was saved.
     "Works correctly" is not an outcome. Split independently failing behaviors
     into separate scenarios when that makes their results clearer. -->

Scenarios are phrased **Given / when / then** in a single sentence. Document the
precondition here and establish it in the executable test or its fixture. No BDD
runner or step-definition layer is required: the project's test command runs
the implemented tests. A scenario with no meaningful precondition starts at
"When". The rows below are examples; use the agreed source contract for actual
status codes, fields, and behavior.

### {Area Name}

| ID | Scenario | Level | Expected outcome |
|---|---|---|---|
| AC-01 | Given the list is empty, when a task is created with a valid title, then it is persisted | integration | 201 with an id; a subsequent read returns that id and title; the list contains exactly one task |
| AC-03 | Given a task exists and is incomplete, when it is marked complete, then its completion is saved | integration | 200, completed=true; a subsequent read confirms completion; its id and title are unchanged |
| VAL-01 | Given the list is empty, when a task is created with an empty title, then it is rejected without saving a task | integration | 400, error "title required"; the list remains empty |
| EDGE-02 | Given a task is already complete, when it is marked complete again, then its saved state remains unchanged | integration | 200, still completed=true; the persisted task, task count, and completion-event count are unchanged |
| | Given..., when..., then... | | |

## Scenario Classification
<!-- Reference catalog IDs; do not define additional scenarios in this table.
     Use categories independently of level, for example functional, validation,
     contract, security, performance, accessibility, recovery, or regression.
     Priority expresses the consequence of failure; Exit Criteria defines gates.
     Each scenario must have an execution mode. For manual checks, provide an
     owner and repeatable procedure in the execution mapping. -->

| Scenario ID | Categories | Priority / risk | Execution mode |
|---|---|---|---|
| | | | Automated / Manual |

<!-- Consider the following only where relevant. Map applicable checks to
     scenarios; record any exclusion and its reason beside the check.
     - Valid/invalid inputs, empty and maximum values, and state transitions.
     - Permissions, tenant boundaries, input abuse, and sensitive-data exposure.
     - Concurrent changes, duplicate requests, retries, timeouts, and cancellation.
     - Recovery after restart or partial failure; data integrity and cleanup.
     - Existing-client compatibility, migrations, rollback, and regression paths.
     - Performance with agreed data volume, load, duration, percentile, and limit.
     - For UI: loading/empty/error states, keyboard access, accessibility, and
       the browsers or viewport sizes required by the Design spec.
     - For time-based behavior: timezone, boundary instants, and daylight saving.
     A scanner, a coverage percentage, or a happy-path test alone does not prove
     all applicable behavior. Do not require every category for every change. -->

## Acceptance Traceability
<!-- Include one row per RFC acceptance criterion and map it to one or more
     scenario IDs. Use the source's stable identifier, or an exact section link
     and criterion text when it has none. Do not reference missing or duplicate
     scenario IDs. Mapping a criterion to a scenario records planned coverage;
     execution evidence is still required to establish that it passes. -->

| RFC acceptance criterion | Covering scenarios |
|---|---|
| | |

### Additional Coverage
<!-- Map every validation rule, documented edge case, and High-severity risk to
     scenarios. Include relevant PRD, Design, interface, security, and migration
     requirements not already represented by an RFC acceptance criterion.
     Every catalog scenario must have a source or a stated risk rationale.
     A missing mapping is a visible gap, not implicit coverage. If evaluation
     is intentionally deferred, record the decision under Exit Criteria. -->

| Source requirement / risk | Covering scenarios | Gap or deferral reference |
|---|---|---|
| | | |

## Fixtures and Test Data
<!-- List fixtures, seed data, factories, fake clocks, or golden inputs and
     state what each one fixes so scenarios can assert exact results. Include
     typical, boundary, and invalid inputs where applicable. Specify reset and
     cleanup rules so tests do not depend on execution order or another test's
     leftovers. Pin clocks, timezone, and random seeds when behavior uses them.
     Describe replaced dependencies and their success/failure responses. Use
     synthetic or approved sanitized data; never embed production credentials. -->

| Fixture / data set | Used by scenarios | Setup and controlled values | Reset / cleanup |
|---|---|---|---|
| | | | |

## Execution and Evidence
<!-- This spec is authored before task planning. Declare stable scenario IDs
     and expected behavior here. Do not add task IDs or predict execution
     selectors: task criteria and implemented tests provide those later. -->

- **Task ownership:** `speed plan` preserves catalog IDs in the existing task criteria, such as `[AC-03] Invalid input returns 400` with `verify_by: test`. Its `files_touched` lists the intended test files. Keep scenarios with no test yet in the catalog.
- **Test identity:** Python functions use `test_ac_03_<behavior>`; Node, Vitest, and Jest use literal test titles `[AC-03] <behavior>`. Several tests across files may carry the same scenario ID. IDs belong on individual tests, not just comments or suite titles.
- **Runner configuration:** `speed.toml` `[eval] test_command` or `test_commands`, with `test_file_patterns` for candidate files; configured subsystem gates can route frontend and backend tests.
- **Generated execution plan:** `speed eval` reads the task criteria and discovers tagged tests, then writes `test-plan.json`. It reads this spec without rewriting it. A task filter selects that task's criteria and tests; feature mode also reports catalog scenarios the planner omitted.
- **Result report:** Per-scenario and per-criterion outcomes, actual commands, test evidence, source revision, and build identity in `report.json`, `summary.md`, and evaluation YAML.

Older specs with explicit Execution and Evidence mapping tables remain readable
when tasks have no tagged criteria. Task-derived selection takes precedence once
criteria carry scenario IDs. An explicit `--test-plan` remains a deliberate
execution override. New specs do not need a Task, Selector, or Test name table.

An automated scenario passes only when its mapped test is discovered, executes,
and its assertions pass. An unrelated green suite or zero discovered tests is
not evidence. If one command covers several scenarios, retain individual test
outcomes where supported; otherwise state the reporting limitation and do not
infer which individual scenario passed from a mixed or failed run. Manual checks
need the actual outcome and reviewer evidence for the identified build.

After a fix, rerun failed scenarios and affected regression checks. Before
release, verify the required scenarios against the integrated build. Preserve
earlier failures and retry history; prose review cannot override failing tests.

## Exit Criteria
<!-- State which conditions and scenario subsets gate merge or release and
     where each gate is enforced. Reference scenario IDs or clearly defined
     sets and agreed limits. State any defect severity threshold explicitly.
     These are required checks, not a claim that CI already enforces them.

     `speed eval` reads the table below, one gate per row, so every gate
     belongs in it. Keep `Gate` as the first column; the status column may be
     headed `Required result` or `Status`, and the evidence column
     `Enforcement` or `Evidence`. A row counts as passed only when its status
     cell reads `pass` and its evidence cell is filled, so an unmet gate blocks
     acceptance instead of disappearing. Replace the rows below with the gates
     this feature needs. -->

| Gate | Required result | Enforcement |
|---|---|---|
| Merge | Required scenarios and regression checks pass | Where the merge gate is enforced |
| Release | Required integrated-build results and quality thresholds are met | Where the release gate is enforced |
| Coverage review | Required source mappings are complete; source changes and unresolved decisions have been reviewed | Who reviews the mappings, and when |
| Exceptions | A failed, blocked, skipped, not-run, or unverified scenario is not a pass. Any permitted release exception records affected IDs, risk, rationale, decision owner, and follow-up target | Where the exception and its follow-up are recorded |
| Flaky tests | Inconsistent outcomes and the repair owner are recorded. Rerunning until green does not erase earlier failures or establish reliable coverage | Who tracks the repair |
