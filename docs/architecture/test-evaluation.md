---
title: Test Spec Template Proposal
description: Why we propose a test spec, what each section covers, and how it supports checking requested behavior with speed eval.
sidebar:
  order: 15
---

For Bookshelf, shipping what was asked includes saving books, showing the right
reading status, and removing a reading list without deleting its books. Each
outcome needs a clear check against the product, technical, and design specs.

We propose introducing a [test-spec template](../../templates/test-spec.md) to
record those checks before evaluating the product. The sections below explain
why we need the template, what it contains, and how its information should help
`speed eval` show whether the implementation meets the agreed requirements.

## Why Propose This Template

The PRD, Design spec, and RFC describe the requested behavior and agreed
solution. A test spec turns the relevant requirements into specific scenarios
with observable results. It gives the author, implementer, and reviewer the
same reference for deciding whether the work is complete.

For example, “remove a book from a reading list” needs checks that the membership
is removed while the book remains saved and available in other lists. Recording
those outcomes removes guesswork from the test. Linking each check to its
requirement makes an untested request visible, even when other tests pass.

The proposed document would live at `specs/tests/<slug>.md`. Its source versions
and expected outcomes should be reviewed before they are used for acceptance.
When a requirement changes, the affected scenarios need review too, so evaluation
checks the behavior the team actually agreed to ship.

## What the Template Covers

The template has eleven main sections. Additional Coverage sits under Acceptance
Traceability and covers requirements and risks beyond the RFC acceptance list.

| Section | What it contains | Why it is needed |
|---|---|---|
| Sources and Review | Links to the exact RFC, PRD, and Design revisions used; spec owner and review details. | Shows which agreed requirements are being checked and who reviewed the test design. |
| Scope | Behavior to verify, existing behavior to preserve, assumptions, and unresolved decisions. | Sets clear boundaries and prevents the test author from guessing missing product decisions. |
| Test Levels | Where each check runs, its tools, environment, and real or replaced dependencies. | Makes clear whether a result proves a function, connected components, or a complete user path. |
| Entry Conditions | Required build, configuration, services, access, data, and blocking prerequisites. | Separates a product failure from a check that could not run. |
| Scenario Catalog | Stable IDs, Given/When/Then scenarios, levels, and exact expected outcomes. | Turns each behavior into a check whose result can be assessed. |
| Scenario Classification | Categories, priority or risk, and automated or manual execution for each catalog ID. | Shows the purpose and importance of a check and how it will be verified. |
| Acceptance Traceability | Every RFC acceptance criterion linked to its covering scenario IDs. | Reveals requested behavior that has no planned test. |
| Additional Coverage | Mappings for validation rules, high-severity risks, edge cases, and relevant requirements from other sources; visible gaps or deferrals. | Catches omissions such as duplicate list entries, partial writes, or missing empty-page behavior. |
| Fixtures and Test Data | Named datasets, fixed clocks, dependency responses, and setup/reset/cleanup rules. | Makes checks repeatable and prevents results from depending on leftover data or the day they run. |
| Execution and Evidence | Links from scenario IDs to tests or manual procedures, runner configuration, and reports for the tested build. | Shows what actually ran and supplies evidence for each result. |
| Exit Criteria | Required merge/release checks, quality limits, coverage review, and rules for exceptions and flaky tests. | Defines what must be satisfied before the work can be accepted. |
| Out of Scope | Excluded or deferred behavior, reasons, risks, and follow-up ownership. | Prevents an untested area from being mistaken for verified behavior. |

Sources and Review records agreement on the test design. Execution and Evidence
points to the results of running it. Keeping these separate avoids treating a
reviewed document as proof that the application passed its checks.

## How a Scenario Describes the Requested Behavior

Each catalog row has a stable ID, a starting condition, an action, and an expected
outcome. Given/When/Then keeps the wording easy to review in a Markdown table.
It does not require a separate Gherkin runner. The implemented test or manual
procedure must establish the starting condition described in the spec.

The [Bookshelf test spec](../../example/specs/tests/bookshelf.md) includes a
creation scenario. Its main assertions are shown here:

| ID | Scenario | Level | Expected outcome |
|---|---|---|---|
| AC-01 | Given an empty database, when `createBook` is called with title "Dune" and author "Frank Herbert", then the book is saved with the agreed defaults. | integration | The returned book has an ID, null ISBN, and status `WANT_TO_READ`; a subsequent read returns the same values; the collection contains exactly one book and one author. |

The follow-up read matters: a successful creation response alone does not show
that the book was stored correctly. An invalid-ISBN scenario would check both
the agreed error response and that no book was saved. Exact outcomes make a
failure explainable instead of relying on phrases such as “works correctly.”

Scenario IDs connect the catalog, source mappings, and execution evidence.
Acceptance Traceability maps each RFC acceptance criterion to one or more IDs.
Bookshelf's technical spec has no acceptance-criteria section, so its test spec
explicitly maps the product spec's criteria instead. Labels such as `F1-1` name
the first criterion under F1; the source revision fixes what that label means.

Additional Coverage maps validation rules, documented edge cases, high-severity
risks, and relevant PRD or Design requirements not already covered there. A
missing mapping stays visible as a coverage gap.

## Why Levels and Categories Are Separate

The proposed starter levels are `unit`, `integration`, and `e2e`. They describe
how much of the application a check exercises. Keep the levels used by the
scenarios and add a project-specific level when needed.

Bookshelf uses the following levels. Its `db` level is a declared extension for
direct database checks; no unit scenarios are listed in this example.

| Level | Bookshelf example | What the result establishes |
|---|---|---|
| integration | Create a book through GraphQL and read it from the test database. | The request handling and storage work together. |
| db | Insert the same book/list pair directly into storage twice. | The database itself enforces the uniqueness rule. |
| e2e | Open the Books page and filter by reading status. | The browser displays the expected books and filter counts. |

Categories such as security, performance, accessibility, and recovery describe
what is being checked. They remain available under Scenario Classification and
can apply at different levels. For Bookshelf, a passing API filter check does
not establish that the Books page displays the correct cards. The integration
and browser scenarios supply different evidence for that request.

## How the Template Supports speed eval

The template supplies the acceptance reference that `speed eval` should use.
Its sections connect the agreed request to evidence for the build being evaluated.

```text
Agreed PRD / Design / RFC revisions
                ↓
Test spec: scenarios, expected outcomes, and coverage mappings
                ↓
Mapped tests or manual checks, using the specified conditions and data
                ↓
speed eval: actual results and evidence for the candidate build
                ↓
Exit Criteria: requirements met, gaps remaining, and release readiness
```

After running `speed eval`, a reviewer should be able to see:

| Evaluation result | How the template makes it possible |
|---|---|
| Which requested behavior was checked and what is missing. | Sources and Review fixes the agreed revisions; Acceptance Traceability and Additional Coverage expose missing mappings. |
| Whether the checks ran under the agreed conditions. | Test Levels, Entry Conditions, and Fixtures and Test Data identify the environment and controlled inputs. Unavailable prerequisites leave affected scenarios blocked. |
| Where the product met or missed an expected outcome. | Scenario Catalog defines the assertions. Every required parameter case must be discovered and pass; manual checks need recorded observations and reviewer evidence. |
| What evidence supports each result. | Execution and Evidence links the scenario to the actual test or procedure, build, source revision, environment, run time, and result. An unrelated passing suite or zero discovered tests proves no scenario. |
| Whether the work meets the agreed acceptance conditions. | Exit Criteria identifies the required scenarios, regressions, coverage, and quality limits to assess on the candidate integrated build. |

The resulting report should let a reviewer follow a requirement to its scenarios
and actual results. Failed, blocked, skipped, not-run, and unverified checks
cannot count as passes. Any permitted release exception needs the affected IDs,
risk, reason, decision owner, and follow-up; the underlying result stays visible.

The template makes the basis for a release decision explicit. Confidence depends
on complete requirement mappings and meaningful tests, so passing results apply
to the reviewed scope and tested build. Exclusions and unresolved requirements
must remain visible when deciding what is ready to ship.

## Bookshelf Example: From Linked Specs to Acceptance

The example already has a [product spec](../../example/specs/product/bookshelf.md),
[technical spec](../../example/specs/tech/bookshelf.md), and
[design spec](../../example/specs/design/bookshelf.md). The
[Bookshelf test spec](../../example/specs/tests/bookshelf.md) connects them through
43 scenarios: 34 integration/database checks and 9 browser checks. It is a draft
with all scenarios recorded as `not_run`.

Fixtures provide five known books: two want-to-read, one reading, and two finished.
Two reading lists provide populated and empty states. Resetting those records
between checks gives dashboard counts, filters, and list operations repeatable
expected results. No fixed clock is needed because these scenarios do not depend
on the current date.

| Source requirement | Covering scenarios | Evidence needed for acceptance |
|---|---|---|
| Product F1-1: add a book with title, author, and optional ISBN. | AC-01, AC-02, EDGE-05 | Reads return the saved values, including defaults and accepted ISBN lengths. |
| Product F2-7: deleting a reading list preserves its books. | AC-13, RISK-04 | The list and its memberships are removed; the five books remain stored. |
| Technical validation rule VR-4: prevent duplicate books in a list. | VAL-05, RISK-02 | Both the GraphQL mutation and a direct database insert reject the duplicate without changing the membership count. |
| Design: show empty and filtered-empty Books page states. | AC-07, EDGE-02 | The browser shows the correct message and action; clearing the filter restores the expected cards. |
| Design: use the specified grid layout at different screen widths. | EDGE-10 | The Books page has the agreed column counts at the tested desktop, tablet, and mobile widths. |

The same spec also exposes gaps that passing tests alone could miss:

| Recorded gap | What the linked specs show | What evaluation must keep visible |
|---|---|---|
| GAP-01: reordering books | Product F2-5 asks for drag or move controls, but the technical spec defines no reorder operation. | No scenario covers this request yet. Other list tests passing cannot establish full F2 coverage. |
| GAP-04: dashboard counts | Product F3-2 asks for counts for all reading statuses; the design lists total, reading, and finished cards only. | AC-15 checks the designed cards but leaves the want-to-read count unverified until the requirement is settled and covered. |
| EC-04: browser tests cannot run | The example's agent file has no frontend test runner configured. | The nine browser scenarios remain blocked; passing backend checks cannot verify the user interface. |

Under the example's Exit Criteria, the open decisions must be resolved, the
missing reorder scenario added, and the test spec reviewed. Required backend
and browser checks then need passing evidence for the integrated build. Even
if all 43 listed scenarios eventually pass, unresolved source gaps would still
prevent a claim that everything requested has been verified.

The [todo due-date test spec](../../specs/tests/todo-due-dates-sample.md) provides
an additional example of fixed clocks, date boundaries, and backend-only coverage.
Both examples describe planned checks, not completed evaluation results.
