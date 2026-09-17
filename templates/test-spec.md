# Test Spec: {Feature Name}

> See [{tech-spec}]({tech-spec}) for the technical contract under evaluation.
<!-- The first "> See [...]" link must point to the RFC whose acceptance
     criteria this evaluation spec covers. Add PRD or sibling RFC references
     as additional blockquote lines when useful. -->

## Scope
<!-- State which RFC and user stories this evaluation spec covers and how the
     scenario catalog is organized. -->

## Test Levels
<!-- Keep only the levels used by scenarios and delete the rest. Add
     project-specific levels when needed. Every Scenario Catalog level must
     match a row in this table. Fill in Tooling with the runner the project
     actually uses; the executor command itself lives in CLAUDE.md under
     ## Quality Gates > ### Test, not here. -->

| Level | Meaning | Tooling | Environment |
|---|---|---|---|
| unit | Pure module logic with dependencies mocked | | Local process |
| integration | Service behavior with real dependencies | | Containerized dependencies |
| contract | Provider and consumer agree on an interface schema | | Contract broker or fixtures |
| e2e | Full request or user path through the running application | | Application and dependencies |
| db | Database constraints, policies, or queries | | Test database |
| ui | Component or browser behavior | | Browser or component runner |
| performance | Latency, throughput, or resource ceilings under stated load | | Load harness |
| security | Authz boundaries, input handling, and data exposure rules | | Scanner or targeted suite |

## Scenario Catalog
<!-- Group scenarios by functional concern. Give every scenario a unique,
     stable ID and an observable outcome.

     SCENARIO PHRASING. Write the Scenario cell as Given / when / then in one
     sentence. This keeps the precondition visible on the page instead of
     buried in the generated test, without adopting a BDD runner or step
     definitions. Plain pytest, go test, or npm test still executes it.

       | AC-03 | Given a task exists, when I mark it complete, then it returns completed | integration | 200, completed=true |

     A scenario with no meaningful precondition may start at "When".

     Expected outcome must be observable: a status code, an error code, a row
     count, a rendered state. "Works correctly" is not an outcome.

     IDs are PREFIX-NN, unique across the file and stable once assigned,
     because traceability rows and generated tests reference them. Conventional
     prefixes: AC- acceptance, RISK- high risk, VAL- validation, EDGE- edge
     case. -->

### {Area Name}

| ID | Scenario | Level | Expected outcome |
|---|---|---|---|
| | | | |

## Acceptance Traceability
<!-- Include one row per RFC acceptance criterion and map it to one or more
     scenario IDs. Do not reference missing or duplicate scenario IDs. -->

| RFC acceptance criterion | Covering scenarios |
|---|---|
| | |

## Fixtures and Test Data
<!-- List fixtures, seed data, factories, fake clocks, or golden inputs and
     state what each one fixes so scenarios can assert exact results. -->

## Exit Criteria
<!-- State which conditions and scenario subsets gate merge or release and
     where each gate is enforced. -->

## Out of Scope
<!-- State what is not evaluated and why so an intentional boundary is not
     mistaken for missing coverage. -->
