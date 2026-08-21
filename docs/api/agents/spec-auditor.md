---
title: Spec Auditor
description: The Spec Auditor runs structural audits of spec files against their type templates.
---

## Mission

The Spec Auditor evaluates specification files for structural completeness, content substance, cross-spec consistency, and scope sizing. It ensures specs are ready to hand off to development before any code is written.

The Spec Auditor is not a code reviewer and not a product guardian. It checks whether the spec is complete, internally consistent, and appropriately sized. It does not judge whether a feature should exist or whether the prose is well-written.

## Invocation

| Property | Value |
|----------|-------|
| Command | `speed audit <spec-file>` |
| Model tier | `support_model` (Sonnet) |
| Tools | Read, Glob, Grep (read-only) |
| Trigger | Manual, or automatically before `speed plan` unless `--skip-audit` is passed |

## Inputs

| Input | Source | Description |
|-------|--------|-------------|
| Spec file content | Path argument | The full spec being audited |
| Type template | `speed/templates/{prd,rfc,design,defect}.md` | Auto-detected by spec path location |
| Product vision | `specs/product/overview.md` | High-level grounding |
| Existing spec list | `specs/` directory scan | For resolving cross-reference links |
| Linked PRD | Resolved from spec header link | PRD content for RFC/Design cross-spec checks |
| Related feature target | Resolved from `Related Feature` field | For defect specs only |

Spec type detection by path: `specs/product/` maps to PRD template, `specs/tech/` to RFC, `specs/design/` to design, `specs/defects/` to defect.

## Outputs

| Output | Location | Description |
|--------|----------|-------------|
| Audit report | Stdout (JSON) | Per-section issues with severity, sizing recommendation, overall status |

## Process

The auditor runs four check levels in order. A failure at any level does not skip subsequent levels.

**Level 1 (Structural).** Checks the spec skeleton against the template: all headings present, no empty sections, no leftover TODO/FIXME markers, no placeholder text (`{Feature Name}`, `TBD`), and all local cross-reference links resolve to existing files.

**Level 2 (Completeness).** Substantive sections must have more than one sentence (or one sentence plus a list/table/code block). Tables must have at least one non-header data row. Checklists must have at least one item.

**Level 3 (Cross-spec consistency, RFC and Design specs only).** For RFCs: every PRD user flow needs a corresponding API endpoint, every PRD entity needs a data model entry, and success criteria must be testable. For Design specs: every PRD flow needs a component/page, every implied page needs a route, and all four UI states (empty, loading, populated, error) must be defined.

**Level 4 (Sizing, PRD and RFC specs only).** Estimates implementation tasks based on user story count, API endpoints, schema changes, and complexity signals. Specs exceeding 10 estimated tasks get a split recommendation with suggested boundaries. Sizing is always a warning, never an error.

## How It Works

The audit pipeline runs in five phases. All context is gathered before the agent runs; the agent has read-only tools but the pipeline assembles the prompt inline.

```
speed audit <spec-file>
    │
    ├─ 1. Detect spec type from path
    │      └─ specs/product/ → prd, specs/tech/ → rfc, etc.
    ├─ 2. Load template + vision + linked specs
    │      ├─ Type template from speed/templates/
    │      ├─ Product vision from specs/product/overview.md
    │      ├─ Linked PRD (from "> See [...](...)" links)
    │      └─ Related feature target (defect specs only)
    ├─ 3. Assemble audit prompt
    ├─ 4. Send to Audit agent (Sonnet, read-only)
    └─ 5. Parse JSON + report + exit code
           ├─ fail (L1 errors) → exit 10
           ├─ warn (L2-4 issues) → exit 0
           └─ pass → exit 0
```

### Phase 1: Spec type detection

`cmd_audit` (`lib/cmd/audit.sh:28-47`) strips everything up to `specs/` in the file path and maps subdirectories: `product/` → prd, `tech/` → rfc, `design/` → design, `defects/` → defect. Unrecognized paths produce a config error.

### Phase 2: Load context

Lines 49-141 load four inputs:

| Input | Resolution method |
|-------|-------------------|
| Type template | `speed/templates/{prd,rfc,design,defect}.md` based on detected type |
| Product vision | `specs/product/overview.md` at project root |
| Linked PRD | Parsed from `> See [...]()` markdown links in the spec, resolved relative to spec directory |
| Related feature | For defect specs: parsed from `**Related Feature:**` field, resolved to product/tech spec paths |

### Phase 3: Prompt assembly

Lines 144-157 build the audit message with five sections: spec under audit, structural template, product vision, linked specs (or "No linked PRD found"), and existing spec file list from the `specs/` directory.

### Phase 4: Agent execution

Lines 165-177 send the prompt via `claude_run` with the audit agent definition (`agents/audit.md`), the support model (Sonnet), and read-only tools. The agent produces JSON matching the output schema without needing an external template.

### Phase 5: Report

Lines 204-282 format the output. Level 1 issues get cross icons (blockers), Level 2+ get warning icons. Sizing recommendations for `split` display the estimated task count and rationale. Exit codes: `EXIT_GATE_FAILURE` for `fail` status (blocks `speed plan`), `EXIT_OK` for `pass` or `warn`.

### Integration with `speed plan`

When called as a pre-plan gate (`plan.sh:262-311`), `cmd_audit` runs in a subshell. A `fail` exit halts planning. The sizing estimate from the audit's `sizing.recommendation` field determines whether the Architect runs single-phase or multi-phase. If the linked PRD exists, it gets audited too.

## Worked Example

An RFC spec at `specs/tech/notifications.md` that references a PRD at `specs/product/notifications.md`.

### The spec under audit

The RFC has all required headings, but the "Data Model" section contains only `TBD` and the "Error Handling" section is completely empty.

### What the agent returns

```json
{
  "status": "fail",
  "spec_type": "rfc",
  "spec_file": "specs/tech/notifications.md",
  "linked_specs": {
    "prd": "specs/product/notifications.md",
    "design": null
  },
  "issues": [
    {
      "level": 1,
      "severity": "error",
      "section": "Data Model",
      "message": "Contains placeholder text 'TBD' — must be replaced with actual schema definition"
    },
    {
      "level": 1,
      "severity": "error",
      "section": "Error Handling",
      "message": "Section is completely empty — must define error states and recovery behavior"
    },
    {
      "level": 3,
      "severity": "warning",
      "section": "API Endpoints",
      "message": "PRD user flow 'Mark notification as read' has no corresponding endpoint in the RFC"
    }
  ],
  "sizing": {
    "estimated_tasks": 7,
    "recommendation": "ok",
    "rationale": "3 API endpoints, 2 models, 1 migration, 1 WebSocket handler"
  }
}
```

### What the user sees

```
═══ Spec Audit ═══
  Spec type: rfc
  Spec file: specs/tech/notifications.md
  Template:  speed/templates/rfc.md
  Linked spec: specs/product/notifications.md
  Vision:    specs/product/overview.md

  Sending to Audit agent...

═══ Audit Report ═══
  ✗ [L1] Data Model — Contains placeholder text 'TBD'
  ✗ [L1] Error Handling — Section is completely empty
  ⚠ [L3] API Endpoints — PRD user flow 'Mark notification as read' has no corresponding endpoint

  Report saved to .speed/logs/audit-1709312000.json

  Audit: FAIL (2 error(s), 1 warning(s))
```

## Constraints

- Read-only access. Cannot modify files.
- Do not judge prose quality. If a section has substance, it passes completeness regardless of writing quality.
- Do not analyze the codebase. Spec quality is the scope, not implementation feasibility.
- Do not auto-fix. Report problems for the human to resolve.
- Treat linked spec absence as a Level 1 error (missing cross-reference link) and skip Level 3 checks.
- Do not invent requirements. Audit against the template and linked specs only.

## Output Schema

```json
{
  "status": "pass | warn | fail",
  "spec_type": "prd | rfc | design | defect",
  "spec_file": "relative path to the spec file",
  "linked_specs": {
    "prd": "relative path or null",
    "design": "relative path or null"
  },
  "issues": [
    {
      "level": 1,
      "severity": "error | warning",
      "section": "heading name",
      "message": "specific, actionable description"
    }
  ],
  "sizing": {
    "estimated_tasks": 0,
    "recommendation": "ok | split",
    "rationale": "reasoning behind the estimate"
  }
}
```

**Status rules:** `fail` when Level 1 errors exist. `warn` when no Level 1 errors but Level 2/3/4 issues exist. `pass` when no issues of any kind. Sizing is `null` for Design and Defect specs.
