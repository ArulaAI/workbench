# Phase 2: Audit Agent

> Parent RFC: [Unified Intake & Defect Pipeline](../unified-intake.md)
> Depends on: [Phase 1: Spec Templates](speed-templates.md)

## Problem

Templates solve the blank-page structure problem. But structure alone doesn't prevent bad specs from entering the pipeline. A human can scaffold a PRD, fill it in, and run `speed plan` — only for the Architect to fail because the RFC is missing API endpoints, the PRD has empty sections, or the spec is too large for a clean task decomposition.

Today, the first quality check on a spec happens inside `speed plan`, when the Architect reviews the RFC. By then the human has written two full specs (PRD + RFC). If the Architect flags problems, that's a lot of rework. There's no earlier, lighter check that catches structural and completeness issues before the human invests in the technical spec.

## Users

### Product
Writes PRDs. Wants to know if the product spec is structurally complete — all sections filled, success criteria measurable, scope clear — before an engineer invests time writing the RFC. Needs specific feedback on what's missing, not a vague thumbs-up.

### Engineering
Writes RFCs. Wants to verify the RFC covers everything the PRD requires — every user flow has API endpoints, the data model supports the described features, nothing fell through the cracks. Wants cross-spec consistency checking before committing to task decomposition.

### Design
Writes design specs. Wants to know all component states are accounted for (empty, loading, populated, error), design tokens reference `globals.css`, and the spec links back to the correct PRD.

## User Stories

| ID | Story | Priority |
|----|-------|----------|
| S1 | As a product person, I want to audit a PRD for structural completeness before an engineer writes the RFC | Must |
| S2 | As an engineer, I want to audit an RFC against its linked PRD to catch coverage gaps | Must |
| S3 | As an engineer, I want to know if my spec is too large and should be split | Must |
| S4 | As an engineer, I want audit to run automatically as part of `speed plan` so I can't skip it | Must |
| S5 | As a product person, I want to see specific issues with section names and actionable messages | Must |
| S6 | As a designer, I want to audit a design spec against its linked PRD | Should |
| S7 | As an engineer, I want to audit a defect report for completeness before running triage | Should |
| S8 | As an engineer, I want to skip audit when I know the spec is ready (`--skip-audit`) | Should |

## User Flows

### Audit a PRD after writing it

1. User scaffolds with `./speed/speed new prd my-feature` and fills in the template
2. User runs `./speed/speed audit specs/product/my-feature.md`
3. Audit Agent detects spec type as PRD from file location
4. Audit Agent loads the PRD template as the structural contract
5. Audit Agent checks: all sections present, no empty headings, no leftover `<!-- TODO -->` markers, no placeholder text
6. Audit Agent estimates sizing from user stories and success criteria count
7. SPEED prints the audit report — pass/warn/fail with specific issues
8. User fixes any issues, re-runs audit if needed

### Audit an RFC against its template and PRD

1. User has written both `specs/product/my-feature.md` and `specs/tech/my-feature.md`
2. User runs `./speed/speed audit specs/tech/my-feature.md`
3. Audit Agent detects spec type as RFC from file location
4. Audit Agent loads the RFC template as the structural contract
5. Audit Agent checks structural completeness: all sections present, no empty headings, no leftover `<!-- TODO -->` markers
6. Audit Agent follows the `> See [product spec]` link to find the PRD
7. Audit Agent checks cross-spec consistency:
   - Every user flow in the PRD has corresponding API endpoints in the RFC
   - Data model relationships support the features described in the PRD
   - Success criteria in the PRD map to testable outcomes in the RFC
8. SPEED prints the audit report with both structural and cross-reference issues
9. User fixes gaps, re-runs audit

### Audit a design spec against its template and PRD

1. User has written `specs/design/my-feature.md` (and `specs/product/my-feature.md` exists)
2. User runs `./speed/speed audit specs/design/my-feature.md`
3. Audit Agent detects spec type as design from file location
4. Audit Agent loads the design template as the structural contract
5. Audit Agent checks structural completeness: all state sections present (empty, loading, populated, error), component inventory filled, design tokens reference `globals.css`
6. Audit Agent follows the `> See [product spec]` link to find the PRD
7. Audit Agent checks cross-spec consistency:
   - Components cover the user flows described in the PRD
   - All pages/routes match the PRD's user flows
8. SPEED prints the audit report
9. User fixes gaps, re-runs audit

### Audit integrated into `speed plan`

1. User runs `./speed/speed plan specs/tech/my-feature.md`
2. SPEED auto-runs audit on the RFC (and linked PRD if found) before the Architect
3. If audit fails → SPEED prints issues, exits. Human fixes specs, re-runs.
4. If audit passes/warns → Architect proceeds with RFC review and task decomposition
5. User can bypass with `./speed/speed plan specs/tech/my-feature.md --skip-audit`

### Audit a defect report

1. User scaffolds with `./speed/speed new defect my-bug` and fills in the report
2. User runs `./speed/speed audit specs/defects/my-bug.md`
3. Audit Agent checks: severity set, Related Feature link resolves, Observed/Expected sections non-empty, reproduction steps present
4. SPEED prints the audit report

## Success Criteria

- [ ] `speed audit <spec-file>` prints a structured audit report (pass/warn/fail with issues)
- [ ] Audit auto-detects spec type from file location (`specs/product/` → PRD, `specs/tech/` → RFC, etc.)
- [ ] Audit checks all template sections are present and non-empty
- [ ] Audit flags leftover `<!-- TODO -->` markers and placeholder text
- [ ] Audit follows cross-reference links and validates they resolve to existing files
- [ ] RFC audit checks coverage against linked PRD (user flows → API endpoints, features → data model)
- [ ] Design spec audit checks all states present (empty, loading, populated, error), component inventory filled, tokens reference `globals.css`, components cover PRD user flows
- [ ] Audit estimates task count and warns (not blocks) if spec would likely produce 10+ tasks, with rationale for why it's large and a suggestion to split — but no prescriptive file breakdown
- [ ] `speed plan` runs audit automatically before the Architect; fails if audit fails
- [ ] `--skip-audit` flag bypasses the automatic audit in `speed plan`
- [ ] Audit output includes section names and actionable messages (not just pass/fail)
- [ ] Audit exits with `EXIT_GATE_FAILURE` (2) on fail, `EXIT_OK` (0) on pass/warn

## Scope

### In Scope
- Audit Agent definition (`speed/agents/audit.md`)
- `speed audit` CLI command (`cmd_audit()` in `speed/speed`)
- Structural completeness checks (sections present, non-empty, no placeholders)
- Cross-reference validation (linked specs exist)
- Cross-spec consistency (RFC covers PRD user flows, data model supports features)
- Design spec consistency (components cover PRD flows, all states accounted for, tokens valid)
- Sizing estimation and split recommendation
- Integration into `speed plan` as a pre-Architect gate
- `--skip-audit` flag

### Out of Scope (and why)
- Prose quality checking — audit checks structure and coverage, not writing quality
- Codebase analysis — that's the Architect's job during `speed plan`
- Auto-fixing issues — audit reports problems, the human fixes them
- Defect pipeline execution — Phase 3
- External adapters — Phase 4+

## Dependencies

- Phase 1 (Spec Templates) — templates must exist as the structural contract the Audit Agent validates against
- Requires a coding agent provider (e.g., Claude Code) for the Audit Agent

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Audit is too strict, rejecting specs that are good enough | Medium | Warn vs. fail distinction. Warnings don't block. `--skip-audit` provides escape hatch. |
| Cross-spec consistency checks produce false positives | Medium | Start with high-confidence checks (missing sections, broken links). Add subtler checks (coverage analysis) iteratively. |
| Sizing estimates are inaccurate | Low | Audit warns, doesn't block on sizing. The Architect's 8-task hard gate is the real enforcement. |
| Users skip audit habitually with `--skip-audit` | Low | Audit is fast (single agent call). If it's too noisy, fix the checks — don't rely on users opting in. |
