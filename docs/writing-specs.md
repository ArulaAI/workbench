---
title: How to Write High-Fidelity Specs
description: Goal-oriented recipes for driving SPEED agents with architectural precision.
sidebar:
  order: 5
---

High-fidelity specs prevent "agent guessing." When an agent has to decide a column type or an API signature on its own, the risk of technical debt increases. These recipes show how to use the spec as a precise remote-control for the orchestrator.

## The High-Fidelity Recipe: Adding a Database Field

A common failure mode occurs when an agent adds a field but misses the index or uses the wrong nullability. Use the **Contract Section** in your tech spec to force the correct implementation.

### Goal
Add a `published_at` timestamp to the `books` table without the agent guessing the schema.

### 1. Update the Product Spec
Add the requirement to `specs/product/bookshelf.md`:
```markdown
### F3: Publication Tracking
**Acceptance criteria:**
- System records the exact date and time a book is published.
- Users can clear the publication date (it is optional).
```

### 2. Update the Tech Spec Contract
Update `specs/tech/bookshelf.md`. Do not just describe the change; define the machine-verifiable contract:
```markdown
## Data Model
#### `books`
| Column | Type | Constraints |
|---|---|---|
| published_at | TIMESTAMP WITH TIME ZONE | NULLABLE |

## Contract
Every field must be traceable to a task.
- `books.published_at` is created by Task: "Add publication tracking".
```

### 3. Run Validation
Verify that your spec changes are consistent across files:
```bash
speed validate specs/
```

### why this works
The Architect reads the `Data Model` table and the `Contract` section. It generates a task that explicitly includes the SQL signature. The Developer agent receives this signature as a constraint rather than a suggestion. Hallucinations are eliminated by structural enforcement.

---

## How to Handle Cross-Cutting Concerns

Large features often require changes across multiple subsystems (e.g., Auth + Analytics).

### Goal
Ensure that every new API endpoint automatically includes an analytics event.

### 1. Define the Constraint
Add a `Cross-Cutting Concerns` section to your Tech Spec:
```markdown
## Cross-Cutting Concerns
- **C1: Analytics Pipeline**: Every GraphQL mutation must emit an `Event` to the `AnalyticsService`.
- **C2: Logging**: Standardize error logs using the `StructuredLogger` helper.
```

### 2. Implementation
The Architect distributes these concerns into the `description` field of every generated task. The Developer agent sees the requirement in its local context, ensuring consistency across parallel branches.

---

## Spec Directory Convention

SPEED organizes specs by concern, each subdirectory serving a distinct purpose:

| Directory | Contains | Audience |
|-----------|----------|----------|
| `specs/product/` | Product requirements, user stories, personas, anti-goals | Product owner / Architect |
| `specs/tech/` | Technical implementation details, data models, contracts | Architect / Developer |
| `specs/design/` | UI/UX specifications, component behavior, interaction flows | Architect / Developer |
| `specs/defects/` | Bug reports with reproduction steps and severity | Defect pipeline |

The `speed audit` command detects spec type from this path structure and applies the appropriate template.

## Multiple Specs for One Feature

Most features involve more than one spec. A product spec captures what to build and why. A design spec pins down how it looks and behaves. A tech spec defines how to implement it. SPEED connects these automatically, but only when they follow one rule: **the files must share the same name**.

```
specs/
├── product/bookshelf.md
├── tech/bookshelf.md
└── design/bookshelf.md
```

When planning begins, SPEED looks for a product spec and design spec with the same filename as the tech spec. If it finds them, all three are loaded together so the agents have the full picture. If one is missing, planning continues without it.

Updating any of the three specs triggers a fresh plan. Even if the tech spec hasn't changed, a revised product spec means the agents should re-evaluate.

### The filename is the link

SPEED matches specs by filename alone. Headers, links, and front-matter inside the file don't affect which specs get paired. If the names don't match, SPEED won't find the connection.

| Product spec | Tech spec | Connected? |
|---|---|---|
| `product/bookshelf.md` | `tech/bookshelf.md` | Yes, names match |
| `product/bookshelf.md` | `tech/bookshelf-search.md` | No, different names |
| `product/bookshelf-search.md` | `tech/bookshelf-search.md` | Yes, names match |

### Splitting a large feature

Some features are too large for a single tech spec. The tech side splits into multiple pieces (child specs), but the product and design context often stays unified. When splitting, give each child its own matching product and design spec so the connection holds.

A feature called "define-ceremony" with five parts:

```
specs/
├── product/
│   ├── define-ceremony-bootstrap.md
│   ├── define-ceremony-editor.md
│   ├── define-ceremony-context.md
│   ├── define-ceremony-contributor.md
│   └── define-ceremony-commitment.md
├── tech/
│   ├── define-ceremony-bootstrap.md
│   ├── define-ceremony-editor.md
│   ├── define-ceremony-context.md
│   ├── define-ceremony-contributor.md
│   └── define-ceremony-commitment.md
└── design/
    ├── define-ceremony-editor.md
    └── define-ceremony-bootstrap.md   ← only the parts that have UI
```

Product specs for children don't need to repeat everything. They can be short documents that reference the parent product context and add acceptance criteria specific to that part. Design specs are only needed for parts that have a distinct user interface.

### Declaring relationships between parts

When a feature is split into multiple specs, each child should declare how it relates to the others at the top of the file:

```markdown
# RFC: Define Ceremony — Bootstrap

> See [product spec](../product/define-ceremony-bootstrap.md) for product context.
> Parent RFC: [context](define-ceremony-context.md)
> Depends on: [context](define-ceremony-context.md)
```

These headers tell SPEED two things: which specs belong to the same family, and which ones must be built before others. Running `speed validate` checks that the parts are consistent with each other (shared interfaces match, acceptance criteria are covered, dependencies make sense).

### Grouping children under one feature

By default, each spec gets its own working area. If the parts of a split feature need to share state (task history, contracts), group them explicitly:

```bash
speed plan specs/tech/define-ceremony-editor.md --feature define-ceremony
```

Without `--feature`, each child operates independently. For most splits, independent operation is fine. Use the flag when children produce artifacts that later children consume.

## The `related:` Front-Matter Field

Specs can declare relationships to other specs using YAML front-matter:

```markdown
---
title: Search Endpoint
related:
  - specs/product/overview.md
  - specs/tech/database.md
---
```

During `speed plan`, the pipeline scores all specs using TF-IDF similarity and structural boosters (front-matter references, cross-references, dependency headers, filename pairing). Specs declared in `related:` receive a boost. The highest-scoring specs are included whole in the Architect's context, never truncated.

## Spec Sizing and the Audit

`speed audit` checks whether a spec is appropriately sized for a single plan cycle. If the estimated task count exceeds the configured threshold, the audit recommends splitting:

```
⚠ Sizing: Consider splitting this spec (~12 tasks)
  Feature touches 4 subsystems with high cross-cluster coordination
```

Split before planning, not after. A spec that produces 12+ tasks risks exceeding the Architect's context window and degrading decomposition quality.

## Required vs Optional Sections

The Architect prompt expects certain sections in a tech spec. Missing required sections trigger L1 (blocker) audit warnings.

| Section | Required | Purpose |
|---------|----------|---------|
| **Goal** | Yes | Single sentence: what changes and why. |
| **Data Model** | For data changes | Table definitions with column types and constraints. Feeds the contract. |
| **Acceptance Criteria** | Yes | Testable outcomes. Each becomes a verification checkpoint. |
| **Out of Scope** | Recommended | Explicit exclusions prevent agents from inventing adjacent features. |
| **Cross-Cutting Concerns** | If applicable | Constraints distributed to every task (logging, auth, analytics). |
| **Contract** | For multi-task features | Machine-verifiable entity definitions. Enforced during integration. |

## The "Out of Scope" Pattern

"Out of Scope" is more than a courtesy section. SPEED's scope enforcement system (1-2 undeclared files = warning, 3+ = `decomposition_error` failure) relies on the Architect correctly bounding each task. An explicit "Out of Scope" section gives the Architect a negative constraint, preventing it from assigning files that belong to adjacent features.

```markdown
## Out of Scope
- Full-text search ranking or relevance scoring (separate feature, not this spec).
- Admin dashboard for search analytics.
- Changes to the existing book creation flow.
```

Without this section, an Architect reading "search endpoint" might reasonably include search analytics or modify the book creation flow to add search indexing.

---

## Summary of Best Practices

| Technique | Purpose | Avoid |
|---|---|---|
| **Numbered Features** | Enables precise task mapping (e.g., `F1.2`). | Vague bullet points. |
| **Acceptance Criteria** | Provides a checklist for the Reviewer agent. | Descriptive prose. |
| **Out of Scope** | Prevents agents from "inventing" helper code. | Silent boundaries. |
| **Contract Tables** | Forces specific SQL/API signatures. | Prose descriptions of fields. |

## Pre-flight Checklist
- [ ] Every feature has a unique ID (e.g., `F1`, `F2`).
- [ ] Acceptance criteria are written as testable outcomes.
- [ ] The "Out of Scope" section explicitly forbids expected-but-unwanted features.
- [ ] Tech spec tables include full types and constraints.
- [ ] `speed validate` reports zero consistency errors.
