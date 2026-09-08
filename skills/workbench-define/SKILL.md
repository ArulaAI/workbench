---
name: workbench-define
description: Reconcile, resume, and connected-audit a Workbench Define feature package. Use when an agent needs to report PRD/Design/RFC progress, identify the next safe Define action, inspect package staleness or ownership, or audit a complete feature name rather than one specification path.
---

# Workbench Define

Use the persisted feature package as the authority. Do not infer stage completion from conversation history or file presence.

## Resume a feature

Run:

```bash
python3 scripts/define.py <feature-name> --project-root <repository> --json
```

Report the returned artifact states, blocker, owner when present, and `next_action`. Enter a focused authoring stage with `workbench draft <prd|design|rfc> <feature-name>` only when the returned prerequisite chain allows it.

The current dependency order is:

1. Finish and publish the PRD.
2. Finish and publish Design against that PRD hash.
3. Finish and publish the RFC against both published hashes.
4. Run the connected audit.
5. Complete Review & commit and ratification.

ADR, evaluation-specification, and final package-ratification gates remain explicit unsupported blockers. Never report `plan_ready` while any is unsupported.

## Audit a package

Run:

```bash
python3 scripts/define.py <feature-name> --audit --project-root <repository> --json
```

Treat the output as read-mostly validation with two durable writes: an immutable timestamped audit report and a latest-report pointer/package summary. Never edit a specification to make an audit pass. Route each finding to its stated artifact, owner, and required action.

Re-running after material artifact changes must produce a new report. A previous report is stale when its frozen artifact hashes differ from the current package.

## Boundaries

- Use `workbench audit <feature-name>` for connected package audit.
- Use `workbench audit <spec-path>` only for focused repair; it cannot establish package readiness.
- Preserve one canonical lowercase hyphenated feature identity under both `specs/<feature>/` and `.speed/.../features/<feature>/`.
- Do not bypass published upstream requirements for Design or RFC.
- Do not claim that publication is human approval. Publication freezes an editorial version; commitment and ratification remain separate evidence.
