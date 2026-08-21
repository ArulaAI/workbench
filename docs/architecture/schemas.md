---
title: Technical Schemas
description: Stripe-style reference for SPEED's internal JSON artifacts.
sidebar:
  order: 13
---

import { Tabs, TabItem } from '@astrojs/starlight/components';

This reference covers the structured JSON artifacts produced and consumed by the context pipeline.

## Architect output schema

The Architect produces a task DAG with expanded per-task fields.

<Tabs>
<TabItem label="Property Reference">

| Property | Type | Requirement | Description |
|---|---|---|---|
| `tasks` | `array` | Required | A list of task definitions that form the implementation plan. |
| `contract` | `object` | Required | Structural definitions (e.g., GraphQL schemas, DB migrations) enforced across all tasks. |
| `validation` | `array` | Required | Global validation rules for the implementation. |
| `cross_cutting_concerns` | `string[]` | Required | Constraints that apply to multiple or all tasks in the plan. |

</TabItem>
<TabItem label="Example Payload">

```json
{
  "tasks": [ { "id": "task_001", ... } ],
  "contract": { "graphql": "type Mutation { ... }" },
  "validation": [ "Titles must be > 3 characters" ],
  "cross_cutting_concerns": [ "Use existing auth middleware" ]
}
```

</TabItem>
</Tabs>

### Per-task object

<Tabs>
<TabItem label="Property Reference">

| Property | Type | Requirement | Description |
|---|---|---|---|
| `id` | `string` | Required | Unique task identifier (e.g., `task_001`). |
| `title` | `string` | Required | Concise name of the task. |
| `description` | `string` | Required | Technical implementation details. |
| `acceptance_criteria` | `object[]` | Required | Verifiable conditions for task completion. |
| `depends_on` | `string[]` | Required | List of task IDs that must be completed first. |
| `files_touched` | `string[]` | Required | Paths to files this task modifies or creates. |

</TabItem>
<TabItem label="Example Payload">

```json
{
  "id": "task_001",
  "title": "Add Search Mutation",
  "description": "Implement searchBooks in src/backend/api/resolvers.py",
  "acceptance_criteria": [
    { "criterion": "Mutation returns list of books", "verify_by": "test" }
  ],
  "depends_on": [],
  "files_touched": ["src/backend/api/resolvers.py"]
}
```

</TabItem>
</Tabs>

## CSG JSON structure

The Codebase Semantic Graph (CSG) is stored at `.speed/context/semantic-graph.json`.

<Tabs>
<TabItem label="Property Reference">

| Property | Type | Description |
|---|---|---|
| `nodes` | `object[]` | Symbol definitions with schema metadata. |
| `edges` | `object[]` | Relationships between symbols (calls, imports, etc.). |
| `clusters` | `object[]` | Domain groupings derived from cohesion analysis. |

</TabItem>
<TabItem label="Node Example">

```json
{
  "id": "src/backend/models/user.py::User",
  "name": "User",
  "kind": "class",
  "file": "src/backend/models/user.py",
  "impact": { "blast_radius": 23, "stability": "bridge" }
}
```

</TabItem>
</Tabs>

## Project Map schema

The Project Map acts as the canonical file registry at `.speed/context/project-map.json`.

<Tabs>
<TabItem label="Property Reference">

| Property | Type | Description |
|---|---|---|
| `generated_at` | `string` | ISO timestamp of the index build. |
| `git_head` | `string` | The git commit hash at the time of the build. |
| `files` | `object[]` | A list of file entries containing paths, languages, and line counts. |

</TabItem>
<TabItem label="File Entry Example">

```json
{
  "path": "src/backend/models/user.py",
  "language": "python",
  "lines": 340,
  "category": "source"
}
```

</TabItem>
</Tabs>

## Spec-alignment schema

Stored at `.speed/features/{feature}/context/spec-alignment.json`.

<Tabs>
<TabItem label="Property Reference">

| Property | Type | Description |
|---|---|---|
| `claims` | `object[]` | assertions extracted from the spec. |
| `status` | `enum` | `confirmed`, `missing`, or `divergent`. |
| `evidence` | `string` | Technical proof for the status. |

</TabItem>
<TabItem label="Claim Example">

```json
{
  "source": { "spec_file": "specs/tech/auth.md", "line": 42 },
  "claim_type": "entity_defined",
  "status": "confirmed",
  "evidence": "CSG: User class found at src/backend/models/user.py::User"
}
```

</TabItem>
</Tabs>
