# RFC: Audit Agent

> See [product spec](../product/speed-audit.md) for product context.
> Depends on: [Phase 1: Spec Templates](speed-templates.md)
> Parent RFC: [Unified Intake & Defect Pipeline](../unified-intake.md)

## Audit Agent

### Agent definition

**File:** `speed/agents/audit.md`
**Model:** `support_model` (sonnet by default)
**Tools:** Read, Glob, Grep (read-only — no writes)

### System prompt context

The Audit Agent receives:
- The spec file to audit (full content)
- The corresponding template (auto-detected from file location, loaded from `speed/templates/`)
- The product vision file (`specs/product/overview.md`)
- List of existing specs in `specs/` (for cross-reference validation)
- For RFCs: the linked PRD content (resolved from the `> See [product spec]` header)
- For Design specs: the linked PRD content (resolved from the `> See [product spec]` header)
- For Defect reports: validation that the `Related Feature` link resolves

### Spec type detection

Auto-detect based on file location:

| File path prefix | Spec type | Template |
|------------------|-----------|----------|
| `specs/product/` | PRD | `speed/templates/prd.md` |
| `specs/tech/` | RFC | `speed/templates/rfc.md` |
| `specs/design/` | Design | `speed/templates/design.md` |
| `specs/defects/` | Defect | `speed/templates/defect.md` |

If the file is not under a recognized prefix, print error and exit with `EXIT_CONFIG_ERROR`.

### Audit checks

The agent performs checks in order of increasing sophistication:

**Level 1: Structural (all spec types)**
- Every section heading from the template exists in the spec
- No sections are empty (heading with no content beneath it)
- No leftover `<!-- TODO -->` markers or placeholder text (`{Feature Name}`, `{dep}`, etc.)
- Cross-reference links resolve to existing files

**Level 2: Completeness (all spec types)**
- Sections that require substance have more than a single sentence (Problem, Data Model, API Surface, etc.)
- Tables have at least one data row (User Stories, Validation Rules, Key Decisions, etc.)
- Checklists have at least one item (Success Criteria)

**Level 3: Cross-spec consistency (RFC and Design only)**

For RFCs (checked against linked PRD):
- Every user flow in the PRD has at least one corresponding API endpoint in the RFC
- Data model entities support the features described in the PRD's user stories
- Success criteria in the PRD map to testable outcomes achievable with the RFC's API surface

For Design specs (checked against linked PRD):
- Components cover the user flows described in the PRD
- All pages/routes map to PRD user flows
- All four state sections are non-empty (empty, loading, populated, error)

**Level 4: Sizing (PRD and RFC only)**
- Agent estimates likely task count based on user stories, API endpoints, data model entities, and overall complexity
- Guideline: each user story typically produces 1-2 tasks, each new entity ~1 task, each endpoint ~0.5 tasks — but the agent uses judgment, not a formula
- If the agent estimates > 8 tasks: warn with rationale and suggest split boundaries
- Sizing is always a warning, never a fail

### Output format

```json
{
  "status": "pass | warn | fail",
  "spec_type": "prd | rfc | design | defect",
  "spec_file": "specs/tech/my-feature.md",
  "linked_specs": {
    "prd": "specs/product/my-feature.md",
    "design": null
  },
  "issues": [
    {
      "level": 1,
      "severity": "error | warning",
      "section": "API Surface",
      "message": "Section is empty — the Architect needs API endpoints to decompose tasks"
    },
    {
      "level": 3,
      "severity": "warning",
      "section": "API Surface",
      "message": "PRD user flow 'invite friend' (S3) has no corresponding mutation in the RFC"
    }
  ],
  "sizing": {
    "estimated_tasks": 14,
    "recommendation": "ok | split",
    "rationale": "5 user stories spanning 3 entities with 8 endpoints — likely 12-15 tasks. Consider splitting invite flow from membership management."
  }
}
```

**Status rules:**
- `fail` — any Level 1 error (missing sections, broken links)
- `warn` — Level 2-4 issues only (thin sections, coverage gaps, sizing)
- `pass` — no issues

## CLI command: `speed audit`

### Command signature

```bash
./speed/speed audit <spec-file>
```

### Implementation

Add `cmd_audit()` function to `speed/speed`:

1. Validate argument: spec file path is provided and file exists
2. Detect spec type from file path (see table above)
3. Load the corresponding template from `speed/templates/`
4. Resolve linked specs:
   - Parse the `> See [product spec](...)` header line to find linked PRD
   - Parse `> Depends on: [...]` to find dependency links
   - For defects: parse `**Related Feature:**` field
5. Assemble agent context: spec content, template content, vision file, linked spec contents, list of existing specs
6. Build Audit Agent system prompt
7. Run agent via `provider_run_json()` (expects JSON output)
8. Parse and validate response with `_require_json`
9. Print audit report:
   - Errors in `COLOR_ERROR` with section names
   - Warnings in `COLOR_WARN` with section names
   - Sizing recommendation if present
   - Final status line: pass/warn/fail
10. Exit with `EXIT_OK` (0) on pass/warn, `EXIT_GATE_FAILURE` (2) on fail

### Output formatting

```
  ✗ [L1] API Surface — Section is empty
  ⚠ [L3] API Surface — PRD user flow 'invite friend' (S3) has no corresponding mutation
  ⚠ [L4] Sizing — Estimated 14 tasks, consider splitting invite flow from membership

  Audit: FAIL (1 error, 2 warnings)
```

Errors use `SYM_CROSS` + `COLOR_ERROR`. Warnings use `SYM_WARN` + `COLOR_WARN`. Level tags help the user understand why the issue was flagged.

## Integration into `speed plan`

Modify `cmd_plan()` to run audit as a pre-Architect gate:

1. Before loading the Architect, run `cmd_audit` logic on the target spec
2. If the spec is an RFC, also audit the linked PRD (if found)
3. If audit status is `fail` → print issues, exit with `EXIT_GATE_FAILURE`
4. If audit status is `warn` → print warnings, continue to Architect
5. If audit status is `pass` → continue to Architect silently
6. `--skip-audit` flag bypasses the audit entirely

### Architect RFC review (unchanged from original spec)

After audit passes, the Architect performs its own RFC review before task decomposition:

1. Load the tech spec (primary input) and sibling specs (product, design)
2. Run the Architect with an RFC review prompt:
   - "Review this RFC for feasibility, codebase fit, completeness, and consistency"
   - "Check: Can this data model support the features in the PRD?"
   - "Check: Does the schema conflict with or duplicate existing tables?"
   - "Check: Are there API endpoints in the PRD that the RFC doesn't define?"
   - "Check: Do the RFC's relationships match the PRD's descriptions?"
3. Architect returns: `{ "approved": true/false, "issues": [...] }`
4. If approved → proceed to task decomposition (same `cmd_plan()` invocation)
5. If not approved → print issues, exit with `EXIT_GATE_FAILURE` (human fixes RFC, re-runs)

### Architect sizing hard gate (unchanged from original spec)

After the Architect produces a task DAG:

1. Count the tasks
2. If task count > 8:
   - Print the task count and a warning
   - Architect proposes a split: sub-feature names, which acceptance criteria go where, dependency ordering
   - Exit with `EXIT_CONFIG_ERROR` (plan not saved)
3. User can override with `--allow-large` flag

## Files changed

| File | Change |
|------|--------|
| `speed/speed` | Add `cmd_audit()`, modify `cmd_plan()` for pre-audit gate + `--skip-audit` flag |
| `speed/agents/audit.md` | New file — Audit Agent definition |
| `speed/agents/architect.md` | Add RFC review prompt section |

## Dependencies

- Phase 1 templates must exist (structural contract for the agent)
- Requires a working agent provider (e.g., Claude Code)
