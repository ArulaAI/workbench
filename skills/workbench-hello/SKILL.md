---
name: workbench-hello
description: >
  Platform proof skill. Returns a fixed greeting to prove that a Workbench CLI
  command and a direct agent skill execute the same canonical implementation.
  Use to verify skill installation; not a module workflow.
version: 0.1.0
---

# workbench-hello

The smallest possible Workbench skill. It exists to prove the platform end to
end (catalog validation, projection, command routing, direct agent discovery,
provenance, idempotency, and repair) before any module skill relies on it.

## When to invoke

- To verify that skills are installed and that CLI and agent routes agree.

## When NOT to invoke

- For any real work. This skill has no domain behavior.

## Inputs

- An optional `name`, defaulting to `World`.

## Behavior

1. Run the one canonical implementation, `scripts/hello.py`, with the given name.
2. Return the structured result below. Do not compose the greeting yourself; the
   helper is the single source of the message, the name default, and the format.

```text
skill: workbench-hello
message: Hello, <name>! Workbench skills are available.
catalog_version: <installed-catalog-version>
surface: <workbench-cli|claude-code|codex|other>
```

## Safety

- Requires no additional permission and inherits the active surface's model and
  controls. It writes no file and touches no module state.
- If the helper cannot run, report the failure. Do not fabricate the greeting.
