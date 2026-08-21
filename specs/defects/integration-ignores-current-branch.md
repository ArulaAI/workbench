# Defect: Integration always targets main, ignoring the user's current branch

Severity: P2
Related Feature: core pipeline

## Observed Behavior

When a user runs SPEED from a feature branch (e.g., `my-feature`), task branches are created from the current branch correctly. But `speed integrate` always merges task branches into `main` (or `master`), determined by `git_main_branch()` in `lib/git.sh`.

The user's feature branch is ignored as an integration target. Task branches contain code that was forked from the feature branch and may depend on changes that only exist there. Merging into `main` (which lacks those changes) can cause conflicts or broken code.

## Expected Behavior

`speed integrate` should merge into the branch the user was on when they started the pipeline, not unconditionally into `main`. The integration target should be configurable in `speed.toml` and default to the branch that was active at `speed plan` time.

Proposed resolution:

1. Record the base branch at `speed plan` time in `.speed/features/<name>/feature.json` (e.g., `"base_branch": "my-feature"`)
2. `speed integrate` reads `base_branch` from feature state instead of calling `git_main_branch()`
3. Add `base_branch` to `speed.toml` as a project-level default (overrides auto-detection, overridden by feature-level state)
4. `MAIN_BRANCH` env var continues to work as the highest-priority override

Priority order: `MAIN_BRANCH` env var > feature-level `base_branch` from plan time > `speed.toml` `base_branch` > `git_main_branch()` auto-detection.

## Reproduction Steps

1. Create a feature branch: `git checkout -b my-feature`
2. Make some changes on `my-feature` that don't exist on `main`
3. Run `speed plan` and `speed run` from `my-feature`
4. Task branches are created from `my-feature` (correct)
5. Run `speed integrate`
6. Integrator merges task branches into `main`, not `my-feature`
7. Merge conflicts or missing dependencies from `my-feature` changes

## Affected Code

- `lib/git.sh:13-31` — `git_main_branch()` function, unconditionally returns `main`/`master`
- `lib/cmd/integrate.sh:117-122` — calls `git_main_branch()` for integration target
- `lib/cmd/integrate.sh:95` — merge-base check against `git_main_branch()`
- `templates/speed-toml.toml` — no `base_branch` configuration option

## Additional Context

The `MAIN_BRANCH` env var provides a workaround (`MAIN_BRANCH=my-feature speed integrate`) but it's not discoverable, not persistent across commands, and requires the user to remember to set it every time. Recording the base branch at plan time is the correct fix because it captures the user's intent when they started the work.
