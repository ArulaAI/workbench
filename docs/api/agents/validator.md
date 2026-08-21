---
title: Validator
description: The Validator agent cross-references all specifications for consistency before planning.
---

## Mission

The Validator reads every specification file in the project and cross-references them for internal consistency and completeness. Its purpose is to catch dropped requirements, missing relationships, and contradictions between product, systems, and technical specs before any code is written.

A `pass` from the Validator means zero critical gaps. Any critical gap produces a `fail`.

## Invocation

| Property | Value |
|----------|-------|
| Command | `speed validate <specs-dir>` |
| Model tier | `support_model` (Sonnet) |
| Trigger | Manual |

## Inputs

| Input | Source | Description |
|-------|--------|-------------|
| All spec files | `specs/` directory | Every product, tech, design, and defect spec in the project |
| Product vision | `specs/product/overview.md` | High-level product identity for grounding |

## Outputs

| Output | Location | Description |
|--------|----------|-------------|
| Consistency report | Stdout (JSON) | Critical gaps, warnings, and entity map |

## Process

1. **Entity relationship completeness.** Every entity mentioned in a product spec (e.g., "teams have an associated project") must have a corresponding foreign key or join table in the systems/tech spec. Missing relationships are critical failures.

2. **Cross-feature consistency.** When Feature A references Feature B, verify Feature B's data model supports that reference. Shared entities must have consistent field definitions. Enum values must match across specs.

3. **Product-to-systems-to-tech traceability.** Every product requirement must have an implementation path in the systems spec. Every table in the systems spec must trace to a product requirement. Every model in the tech spec must match the systems spec schema. Requirements with no technical implementation are flagged.

4. **Data model integrity.** All foreign keys reference existing tables. Join tables have both FKs. Nullable/required constraints are consistent. Default values are defined where needed.

5. **API/query completeness.** Every entity in a UI spec has a corresponding GraphQL query/mutation. Response types include all fields the UI needs. Mutations exist for all user actions described in product specs.

## How It Works

The Validator is not yet integrated into a CLI command. The intended invocation flow is described here based on the agent prompt definition (`agents/validator.md`). When integrated, it would follow this pipeline:

```
speed validate <specs-dir>
    │
    ├─ 1. Scan specs/ directory
    │      └─ Enumerate all .md files under product/, tech/, design/, defects/
    ├─ 2. Load product vision
    │      └─ specs/product/overview.md
    ├─ 3. Assemble cross-reference prompt
    │      └─ All spec contents + vision document
    ├─ 4. Send to Validator agent (Sonnet, read-only)
    ├─ 5. Parse JSON report
    └─ 6. Pass/fail gate
           ├─ fail → list critical gaps with source citations
           └─ pass → all entity relationships verified
```

### Intended behavior

The Validator reads every spec file completely, building an entity map as it goes. For each entity mentioned in a product spec, it traces forward through systems and tech specs to verify a corresponding data structure exists. The reverse direction also applies: orphaned technical entities with no product requirement get flagged.

Cross-feature references receive special treatment. When Feature A's spec mentions Feature B, the Validator reads Feature B's spec in full and verifies the data model supports the reference. Shared entities (those appearing in multiple feature specs) must have consistent field definitions and enum values across all references.

### Current status

The agent definition exists at `agents/validator.md` with a complete prompt and output schema, but no `cmd_validate` function or `speed validate` command has been implemented. Running `speed validate` would currently fail with an unknown-command error. The [Spec Auditor](/docs/api/agents/spec-auditor/) handles per-file structural checks, while the Validator is designed for cross-file consistency checks that the Auditor does not perform.

## Worked Example

Three feature specs exist in a project: `user-profiles`, `team-management`, and `notifications`.

### The specs under validation

The `user-profiles` PRD states: "Users belong to teams. A user's profile page shows their team name."

The `team-management` PRD states: "Teams have a name, description, and owner. The owner is a User."

The `notifications` PRD states: "Users receive notifications when added to a team."

The tech spec for `team-management` defines a `teams` table with columns `id`, `name`, `description`, `owner_id (FK → users)`. But it has no `team_members` join table.

### What the Validator would return

```json
{
  "status": "fail",
  "summary": "Missing join table for user-team membership. Product spec says 'users belong to teams' but no team_members table exists in any tech spec.",
  "critical_gaps": [
    {
      "type": "missing_relationship",
      "source_spec": "specs/product/user-profiles.md",
      "source_text": "Users belong to teams",
      "expected_in": "specs/tech/team-management.md",
      "description": "The phrase 'belong to' implies a many-to-many relationship requiring a team_members join table. Only owner_id (one-to-one) exists."
    },
    {
      "type": "missing_query",
      "source_spec": "specs/product/user-profiles.md",
      "source_text": "A user's profile page shows their team name",
      "expected_in": "specs/tech/user-profiles.md",
      "description": "No GraphQL query or API endpoint exists to fetch a user's team. The tech spec has no join path from users to teams except ownership."
    }
  ],
  "warnings": [
    {
      "type": "inconsistency",
      "description": "notifications spec references 'added to a team' but no team membership mechanism exists to trigger this event"
    }
  ],
  "entity_map": {
    "users": {
      "defined_in": ["specs/tech/user-profiles.md"],
      "referenced_by": ["specs/product/user-profiles.md", "specs/product/team-management.md", "specs/product/notifications.md"],
      "relationships": ["teams (FK: owner_id)"],
      "missing_relationships": ["teams (membership — no join table)"]
    },
    "teams": {
      "defined_in": ["specs/tech/team-management.md"],
      "referenced_by": ["specs/product/team-management.md", "specs/product/user-profiles.md"],
      "relationships": ["users (FK: owner_id)"],
      "missing_relationships": ["users (membership — no join table)"]
    }
  }
}
```

### What the user would see

```
✗ Validation FAILED — 2 critical gap(s)

  ✗ missing_relationship: "Users belong to teams" (user-profiles PRD)
    Expected in: specs/tech/team-management.md
    No team_members join table exists

  ✗ missing_query: "A user's profile page shows their team name" (user-profiles PRD)
    Expected in: specs/tech/user-profiles.md
    No query path from users to teams except ownership

  ⚠ notifications spec references team membership but no mechanism exists

  Fix the gaps above and re-run: speed validate
```

## Constraints

- Read-only access. Cannot modify files.
- Every "associated with", "belongs to", "links to", "has many", or "part of" phrase in a product spec implies a foreign key or join table. If it is missing from the systems/tech spec, that is a critical gap.
- Must read every spec file completely. No skimming.
- Cross-reference aggressively: if Feature A mentions Feature B, read Feature B's spec in full.

## Output Schema

```json
{
  "status": "pass | fail",
  "summary": "Brief overall assessment",
  "critical_gaps": [
    {
      "type": "missing_relationship | missing_field | missing_query | inconsistency | orphaned_requirement",
      "source_spec": "which spec defines the requirement",
      "source_text": "exact quote from the spec",
      "expected_in": "which spec should have the implementation",
      "description": "what is missing and why it matters"
    }
  ],
  "warnings": [
    { "type": "type", "description": "non-critical inconsistency or potential issue" }
  ],
  "entity_map": {
    "entity_name": {
      "defined_in": ["spec files"],
      "referenced_by": ["spec files"],
      "relationships": ["entity_name (FK: column_name)"],
      "missing_relationships": ["description of missing link"]
    }
  }
}
```
