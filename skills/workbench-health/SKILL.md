---
name: workbench-health
description: >
  Verify that Workbench skills were imported into the current project and are
  intact and ready for the active agent to use. Run after initialization or
  skill sync, or when project skill availability is uncertain.
---

# workbench-health

Verify the installed Workbench skill projection without changing project state.

## Run the check

The project root is the nearest directory at or above the working directory
that contains `.speed/`. In a git checkout, `git rev-parse --show-toplevel`
prints that same path. Start there and run the helper through an explicit
interpreter:

```bash
cd "$(git rev-parse --show-toplevel)"
python3 .claude/skills/workbench-health/scripts/health.py --project-root . --json
```

Projection copies file bytes and not the executable bit, so the helper runs as
an argument to an interpreter rather than as a command of its own. Where a
project pins its own interpreter, use that path (`.venv/bin/python3`) instead
of `python3`.

The command above names the Claude Code projection root. Substitute the root
this skill was projected into:

| Harness | Helper path from the project root |
|---|---|
| Claude Code | `.claude/skills/workbench-health/scripts/health.py` |
| Codex | `.agents/skills/workbench-health/scripts/health.py` |
| GitHub Copilot | `.github/skills/workbench-health/scripts/health.py` |

Surface detection needs no argument: the helper reads its own location. Pass
`--surface claude|codex|copilot` only to check a harness other than the one it
was projected into.

## Report the result

`--json` prints the structured result. Exit status 1 means the projection is
unhealthy, not that the helper failed.

```json
{
  "skill": "workbench-health",
  "status": "unhealthy",
  "message": "Workbench skills are not ready to use.",
  "catalog_version": "0.1.0",
  "surface": "claude_code",
  "skills": ["workbench-health"],
  "issues": ["workbench-health: modified SKILL.md"],
  "remediation": ["Review or back up local edits, then run `workbench skills sync --surface claude_code --force`."]
}
```

Pass `status` and `message` through as written. A `healthy` result means the
Workbench skills were imported successfully and are ready to use. On
`unhealthy`, list every entry in `issues`, quote every command in
`remediation`, and do not claim the skills are available.

Repairs are issue-specific, which is why they come from the helper rather than
from this file: a locally edited projection needs `--force`, a broken manifest
has to be restored before any sync can help, and an unsupported harness needs
`workbench init --harness` first. Never substitute a repair of your own. When
the user wants the state of every managed projection rather than this project's
readiness, point them at `workbench skills doctor`.

## Safety

- No additional permission is required. The helper reads
  `.speed/skills/manifest.json` and the projected skill directory for the
  selected surface, refusing symlinks and any path that resolves outside the
  project.
- It writes no file and touches no module state.
- If the helper cannot run, report the failure. Do not fabricate a healthy
  result.
