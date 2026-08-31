---
name: workbench-health
description: >
  Verify that Workbench skills were imported into the current project and are
  intact and ready for the active agent to use. Run after initialization or
  skill sync, or when project skill availability is uncertain.
---

# workbench-health

Verify the installed Workbench skill projection without changing project state.

## Behavior

1. Run `scripts/health.py --project-root <project-root>`. The helper infers
   its own surface from where it was projected; pass `--surface` only to
   check a different harness.
2. Return the helper's structured result without rewriting its status or
   message. The helper checks the project skill manifest and verifies every
   recorded projected file.
3. On `healthy`, tell the user that Workbench skills were imported successfully
   and are ready to use.
4. On `unhealthy`, show every reported issue and recommend
   `workbench skills sync`; do not claim the skills are available.

```text
skill: workbench-health
status: <healthy|unhealthy>
message: <readiness summary>
catalog_version: <installed-catalog-version>
surface: <claude_code|codex|copilot|other>
skills: <installed Workbench skill names>
issue: <missing or modified projection; present only when unhealthy>
```

## Safety

- Require no additional permission. Read only `.speed/skills/manifest.json` and
  the projected skill directory for the selected surface.
- Write no file and touch no module state.
- If the helper cannot run, report the failure. Do not fabricate a healthy
  result.
