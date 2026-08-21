# RFC: Observation Infrastructure

> See [product spec](../product/speed-observations.md) for product context.
> Depends on: Existing SPEED pipeline (`speed integrate`, task JSON, review JSON, guardian logs, `lib/context/layer2.py`)

## Basic Example

A complete `speed learn` session after integrating a 5-task feature:

```bash
# 1. Integration completes — operator is prompted
./speed integrate
# ...
# Integration complete. Run observation extraction? [Y/n] y

# 2. Extraction runs automatically
# Reading artifacts for feature speed-security...
#   Step 1/10: Task outcomes ............ 5 tasks (1 retry, 4 clean)
#   Step 2/10: Review findings .......... 3 findings classified
#   Step 3/10: Guardian verdicts ........ 1 override (4 cleared, no obs)
#   Step 4/10: Verify findings .......... 1 spec drift
#   Step 5/10: Coherence issues ......... 1 interface mismatch
#   Step 6/10: Security findings ........ 1 medium
#   Step 7/10: Context effectiveness .... 1 miss, 1 waste
#   Step 8/10: Decomposition quality .... 1 boundary mismatch
#   Step 9/10: Success observations ..... 4 clean passes
#   Step 10/10: Pattern matching ........ 1 recurring pattern
#
# Wrote 16 observations to .speed/memory/observations/speed-security.jsonl
# Summary: 1 retry, 3 review findings, 1 override, 1 verify drift,
#          1 coherence issue, 1 security finding, 1 context miss,
#          1 context waste, 1 decomp miss, 4 successes, 1 pattern match

# 3. Manual re-run (idempotent — no duplicates)
./speed learn --feature speed-security
# All 16 observations already exist. Nothing new to write.

# 4. Aggregate view across features
./speed learn --summary
# 4 features observed. 47 total observations.
# Top patterns:
#   missing template update (3 features, weight 8.5)
#   isinstance guard missing (2 features, weight 4.5)
# By type: 6 retries, 12 review findings, 4 overrides, 3 verify drifts,
#          2 coherence issues, 2 security findings, 18 successes
```

Each observation is a self-contained JSONL line:

```jsonl
{"id":"sha256:a7c3f...","feature":"speed-security","stage":"developer","task_id":"3","timestamp":"2026-03-06T14:22:00Z","observation_type":"retry","detail":{"what_happened":"Missing template update for lib/toml.py change","evidence":"retry_count=2, reviewer flagged on attempt 1","resolution":"Added template update in retry 1","files_involved":["lib/toml.py","templates/speed-toml.toml"]},"weight":3.0}
```

## System Flow

```
                         speed integrate (success)
                                  │
                                  ▼
                    ┌─────────────────────────┐
                    │   Prompt: Run learning?  │
                    │       [Y/n] default Y    │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │      cmd_learn()         │
                    │   lib/cmd/learn.sh       │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │    learn_bridge.sh       │
                    │    (bash → python)       │
                    └────────────┬────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────┐
│                    extract.py pipeline                          │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  STEP 1: Task outcomes                                   │  │
│  │  Read <id>.json → retry, duration, files_touched           │  │
│  └──────────────┬───────────────────────────────────────────┘  │
│                 │ task metadata (retry_count, files)            │
│                 ▼                                               │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  STEP 2: Review findings                                 │  │
│  │  Read review-<id>.json → issues[] array                    │  │
│  │  ┌────────────────────────────────┐                       │  │
│  │  │  classify.py                   │                       │  │
│  │  │  TF-IDF prototypes (90%)  ─────┤                       │  │
│  │  │  embedding cascade         ─────┤──→ category            │  │
│  │  │  sklearn (if trained)      ─────┤                        │  │
│  │  │  unclassified (fallback)  ──────┘                        │  │
│  │  └────────────────────────────────┘                       │  │
│  └──────────────┬───────────────────────────────────────────┘  │
│                 │ finding categories                            │
│                 ▼                                               │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  STEP 3: Guardian verdicts                               │  │
│  │  Primary: read logs/guardian-*.json for verdicts + flags  │  │
│  │  Fallback: task JSON review_feedback → "GUARDIAN REJECTED"│  │
│  └──────────────┬───────────────────────────────────────────┘  │
│                 │                                               │
│                 ▼                                               │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  STEPS 4-6: Verify / Coherence / Security  (parallel)    │  │
│  │  Read plan-verification.log → spec_requirements[].status  │  │
│  │  Read coherence.log → interface_mismatches[]              │  │
│  │  Read security-audit.json → findings[]                    │  │
│  └──────────────┬───────────────────────────────────────────┘  │
│                 │                                               │
│                 ▼                                               │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  STEP 7: Context effectiveness                           │  │
│  │  code-context.json file list  ←──compare──→  git diff     │  │
│  │  Δ = miss (modified but not provided)                     │  │
│  │  Δ = waste (provided but not modified)                    │  │
│  │  ⚠ code-context.json does not reliably persist — step     │  │
│  │    skipped with warning when file is missing              │  │
│  └──────────────┬───────────────────────────────────────────┘  │
│                 │                                               │
│                 ▼                                               │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  STEP 8: Decomposition quality                           │  │
│  │  task plan files_declared  ←──compare──→  actual files     │  │
│  └──────────────┬───────────────────────────────────────────┘  │
│                 │                                               │
│                 ▼                                               │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  STEP 9: Success observations                            │  │
│  │  Tasks with: retry_count=0, no context misses, guardian   │  │
│  │  cleared, no verify/coherence/security issues             │  │
│  └──────────────┬───────────────────────────────────────────┘  │
│                 │                                               │
│                 ▼                                               │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  STEP 10: Pattern matching                               │  │
│  │  Group current + prior observations by                    │  │
│  │  (type, files_hash, category)                             │  │
│  │  Flag groups with 3+ distinct features                    │  │
│  └──────────────┬───────────────────────────────────────────┘  │
│                 │                                               │
└─────────────────┼──────────────────────────────────────────────┘
                  │
                  ▼
     ┌───────────────────────────┐
     │  observation_id()         │
     │  SHA-256 per observation  │
     └────────────┬──────────────┘
                  │
                  ▼
     ┌───────────────────────────┐
     │  write_observations()     │
     │  Load existing IDs → set  │
     │  Skip duplicates          │
     │  Append new lines (JSONL) │
     │  fsync                    │
     └────────────┬──────────────┘
                  │
                  ▼
     .speed/memory/observations/
       speed-security.jsonl          ← append-only
       speed-auth.jsonl
       ...
```

**Data flow between extraction and downstream consumers:**

```
.speed/features/{name}/              .speed/memory/
  tasks/<id>.json ───────────┐         observations/*.jsonl
    (fallback for guardian   │              │
     rejections after prune) │              │ (Phase 3: Synthesis reads)
  logs/guardian-*.json ──────┤              │
  logs/review-<id>.json ─────┤              │
  logs/security-audit.json ──┤              │
  logs/plan-verification.log ┤──→ extract ──→│
  logs/coherence.log ────────┤              ▼
git diff (feature branch) ───┘     architect-learnings.json
                                   developer-learnings.json
                                   reviewer-learnings.json
                                   guardian-learnings.json
                                   context-learnings.json
```

Extraction writes observations. Synthesis (Phase 3, separate feature) reads them and produces per-agent learnings files. The observation JSONL files are the interface contract between the two systems.

## Extraction Steps

Each step reads specific pipeline artifacts, produces typed observations, and is independently testable. Steps run sequentially (Step 1's task dict feeds Steps 2-9), but Steps 4-6 are internally parallel. Each section below covers the step's goal, source data, solution, observation types produced, weights, known limitations, and test expectations.

### Step 1: Task Outcomes

**Goal:** Read every task JSON in the feature, detect retries, gate failures, agent concerns, and unattributed changes. Build the `tasks` dict that all subsequent steps depend on.

**Source data:**

| Artifact | Path | What it provides |
|----------|------|------------------|
| Task JSON | `.speed/features/<name>/tasks/<id>.json` | `retry_count`, `timeout_count`, `agent_model`, `status`, `review_verdict`, `started_at`, `completed_at`, `files_touched`, `concerns[]`, `error`, `branch` |
| Gate logs | `.speed/features/<name>/logs/gate-{label}-{epoch}.log` | Gate pass/fail output. Correlated to tasks by timestamp window, not by the task `error` field (which upstream doesn't reliably set). |
| Git log | Feature branch vs. task branches | Commits on the feature branch not reachable from any task branch are unattributed. |

**Solution:**

Two functions: `_step1_task_outcomes()` reads task JSONs and produces retry/gate_failure/agent_concern observations. `_step1_unattributed_changes()` compares git commit SHAs across branches.

Retry detection has two paths:
- **Explicit:** `retry_count > 0` in task JSON.
- **Implicit:** `review_verdict == "request_changes"` with no `retry_count`. This catches tasks where `task_request_changes()` didn't increment the counter. When only implicit detection fires, `retry_count` is set to 1 in the observation.

Gate failure detection scans `logs/gate-*.log` files within a 60-second window of the task's start/end timestamps. Passing gates contain `"All checks passed!"` or are empty. Failing gates have their first 5 non-empty lines captured as the error summary. File and line are parsed from eslint-style (`file.ext 42:10 error`) or pytest-style (`FAILED test.py::`) output.

Agent concerns are extracted from the `concerns[]` array in task JSON. The `predictive` flag is set when the task was later rejected by the reviewer, meaning the agent anticipated its own failure. `decisions[]` (also in task JSON) are not extracted — decisions describe approach, concerns flag risk.

Unattributed changes compare `git log main..feature/<name>` against the union of `git log main..<task-branch>` for all tasks. Commits in the feature set but not in any task set are unattributed. Files touched by those commits are collected via `git diff-tree`.

```python
def _step1_task_outcomes(feature: str, tasks_dir: Path, logs_dir: Path,
                         result: ExtractResult) -> dict[str, dict]:
    """Step 1: Read task JSON files, produce retry/gate_failure/agent_concern observations.

    Returns a dict of task_id -> task_data for use by later steps.
    """
    tasks: dict[str, dict] = {}

    if not tasks_dir.is_dir():
        result.warnings.append("No tasks/ directory found")
        return tasks

    for task_file in sorted(tasks_dir.glob("*.json")):
        task = _read_json(task_file)
        if not isinstance(task, dict):
            result.errors.append(f"Malformed task JSON: {task_file.name}")
            continue

        task_id = str(task.get("id", task_file.stem))
        tasks[task_id] = task

        # ── Retry detection ──────────────────────────────────────
        retry_count = task.get("retry_count", 0) or 0
        timeout_count = task.get("timeout_count", 0) or 0
        has_explicit_retry = retry_count > 0
        has_implicit_retry = (
            task.get("review_verdict") == "request_changes"
            and task.get("status") in ("done", "pending")
        )
        if has_explicit_retry or has_implicit_retry:
            if not has_explicit_retry:
                retry_count = 1
            duration = _duration_seconds(task)
            evidence_parts = []
            if has_explicit_retry:
                evidence_parts.append(f"retry_count={retry_count}")
            if has_implicit_retry and not has_explicit_retry:
                evidence_parts.append("review_verdict=request_changes")
            if timeout_count > 0:
                evidence_parts.append(f"timeout_count={timeout_count}")
            detail = {
                "retry_count": retry_count,
                "timeout_count": timeout_count,
                "agent_model": task.get("agent_model", ""),
                "what_happened": _get_retry_reason(task),
                "resolution": f"status={task.get('status', 'unknown')}",
                "files_involved": task.get("files_touched", []),
                "duration_seconds": duration,
                "evidence": ", ".join(evidence_parts),
            }
            result.observations.append(
                _make_obs(feature, "developer", task_id, "retry", detail)
            )

        # ── Gate failure detection ───────────────────────────────
        gate_logs = _find_gate_logs(task, logs_dir)
        for gate_name, error_summary, file_path, line_num in gate_logs:
            detail = {
                "gate": gate_name,
                "error_summary": error_summary[:500],
                "file": file_path,
                "line": line_num,
            }
            result.observations.append(
                _make_obs(feature, "developer", task_id,
                          "gate_failure", detail)
            )

        # ── Agent concerns ───────────────────────────────────────
        for concern in task.get("concerns", []):
            if not isinstance(concern, str) or not concern.strip():
                continue
            detail = {
                "concern": concern[:500],
                "agent_model": task.get("agent_model", ""),
                "task_status": task.get("status", ""),
                "review_verdict": task.get("review_verdict", ""),
                "predictive": task.get("review_verdict") == "request_changes",
            }
            result.observations.append(
                _make_obs(feature, "developer", task_id,
                          "agent_concern", detail)
            )

    return tasks
```

**Observation types produced:**

| Type | Stage | Weight | When produced |
|------|-------|--------|---------------|
| `retry` | developer | 3.0 | `retry_count > 0` or `review_verdict == "request_changes"` |
| `gate_failure` | developer | 2.0 | Gate log file within task's time window contains failure output |
| `agent_concern` | developer | 1.0 | Non-empty string in task JSON `concerns[]` |
| `unattributed_changes` | developer | 1.0 | Feature branch commits not in any task branch |

**Known limitations:**

- Gate log correlation uses a 60-second window. If two tasks overlap within 60 seconds (unlikely but possible for fast tasks), a gate log could be attributed to the wrong task.
- Unattributed change detection requires the feature branch to still exist in git. If the branch was deleted before extraction, this sub-step is silently skipped.
- `timeout_count` and `agent_model` depend on fields that upstream may not always set. Missing values default to 0 and `""`.

**Test expectations:**

- Task with `retry_count=0` and `review_verdict=approve` produces no retry observation
- Task with `retry_count=2` produces retry with correct `timeout_count`, `agent_model`, `evidence`
- Task with `review_verdict=request_changes` and no `retry_count` produces retry (implicit detection)
- Task with `retry_count=1` and `review_verdict=approve` produces retry with `what_happened="Reviewer requested changes (resolved)"`
- Gate log files with failures produce `gate_failure` observations (correlated by timestamp window)
- Task with `concerns[]` and `review_verdict=request_changes` produces `agent_concern` with `predictive=true`
- Task with missing `started_at` or `completed_at` produces `duration_seconds=None`
- Malformed task JSON is skipped with error logged
- Feature branch commits not in any task branch produce `unattributed_changes`

---

### Step 2: Review Findings

**Goal:** Read review JSON files, classify each finding into a category, and extract structured reviewer output (spec verification, out-of-scope items, strengths). The classification feeds synthesis so it can group findings by type across features.

**Source data:**

| Artifact | Path | What it provides |
|----------|------|------------------|
| Review JSON | `.speed/features/<name>/logs/review-<id>.json` | `issues[]` (free-text findings), `spec_verification[]`, `missing_from_spec[]`, `out_of_scope[]`, `strengths[]` |
| Task dict | From Step 1 | `retry_count`, `review_verdict` — used to compute `confirmed` and `led_to_retry` |

Review JSON files are multi-line JSONL where each line contains disjoint top-level keys. `_read_json()` handles this by merging all lines via `dict.update()`.

**Solution:**

Five source arrays produce `reviewer_finding` observations with different classification rules:

| Source array | Category | How classified |
|--------------|----------|---------------|
| `issues[]` | Varies | `classify_fn()` — prototype matching, see [Review Finding Classification](#review-finding-classification) |
| `spec_verification[]` | `spec_alignment` | Hardcoded. Only non-satisfied items (`satisfied != true`). |
| `missing_from_spec[]` | `spec_alignment` | Hardcoded. Requirements the reviewer couldn't verify. |
| `out_of_scope[]` | `scope` | Hardcoded. Work beyond task boundaries. |
| `strengths[]` | `strength` | Hardcoded. Positive observations (weight 0.5). |

Two boolean fields distinguish signal strength:

- **`confirmed`** is true when `retry_count > 0` or `review_verdict == "request_changes"`. For structured arrays (`spec_verification`, `missing_from_spec`, `out_of_scope`, `strengths`), `confirmed` is always true — these are the reviewer's explicit judgments, not ambiguous findings.
- **`led_to_retry`** is true only when `retry_count > 0`.

These fields are independent. A finding can be confirmed (the reviewer requested changes) without leading to a retry (the task was not re-run). Weight is 1.5 for confirmed findings, 0.5 for dismissed.

```python
def _step2_review_findings(feature: str, logs_dir: Path,
                            tasks: dict[str, dict],
                            result: ExtractResult,
                            classify_fn=None) -> None:
    """Step 2: Read review JSON files, classify and produce reviewer_finding observations."""
    for task_id in tasks:
        review_path = logs_dir / f"review-{task_id}.json"
        if not review_path.exists():
            continue

        review = _read_json(review_path)
        if not isinstance(review, dict):
            result.warnings.append(f"Malformed review JSON: review-{task_id}.json")
            continue

        issues = review.get("issues", [])
        if not issues:
            continue

        task = tasks[task_id]
        retry_count = task.get("retry_count", 0) or 0
        review_verdict = task.get("review_verdict", "")

        for issue in issues:
            if not isinstance(issue, dict):
                continue

            finding_text = f"{issue.get('message', '')} {issue.get('suggestion', '')}"

            category = "unclassified"
            if classify_fn:
                try:
                    cr = classify_fn(finding_text)
                    category = cr.category
                except Exception:
                    pass

            confirmed = retry_count > 0 or review_verdict == "request_changes"
            led_to_retry = retry_count > 0
            weight = 1.5 if confirmed else 0.5

            detail = {
                "category": category,
                "finding": issue.get("message", ""),
                "confirmed": confirmed,
                "led_to_retry": led_to_retry,
                "severity": issue.get("severity", ""),
                "suggestion": issue.get("suggestion", "")[:500],
                "file": issue.get("file", ""),
                "line": issue.get("line", 0),
            }
            result.observations.append(
                _make_obs(feature, "reviewer", task_id,
                          "reviewer_finding", detail, weight=weight)
            )

        # ── Structured arrays (spec_verification, missing_from_spec,
        #    out_of_scope, strengths) omitted for brevity — see extract.py:540-641
```

**Observation types produced:**

| Type | Stage | Weight | When produced |
|------|-------|--------|---------------|
| `reviewer_finding` | reviewer | 1.5 (confirmed) / 0.5 (dismissed) | Each issue in `issues[]`, each non-satisfied item in `spec_verification[]`, each item in `missing_from_spec[]` and `out_of_scope[]` |
| `reviewer_finding` (strength) | reviewer | 0.5 | Each item in `strengths[]` |

**Known limitations:**

- Classification accuracy is unverified on day one. The prototype matcher handles ~90% of findings; unclassified findings get `category: "unclassified"`. Misclassification affects synthesis grouping but not data integrity.
- `suggestion` is truncated to 500 characters. Other detail fields are not truncated.
- If a review JSON file has no `issues[]` key, the structured arrays (`spec_verification`, etc.) are still processed. But if the file is entirely malformed (not valid JSON/JSONL), the whole file is skipped with a warning.

**Test expectations:**

- Review JSON with 3 issues produces 3 `reviewer_finding` observations
- Each finding has a classified category (not `"unclassified"`) via prototype matching
- Missing review JSON skips step (warning, no error)
- Review JSON with `verdict=approve` and no `issues[]` produces nothing
- JSONL review file (multiple JSON lines) is merged via `dict.update()`
- Finding with `retry_count > 0` has `confirmed=true` and `led_to_retry=true`
- Finding with `review_verdict=request_changes` and no retry has `confirmed=true`, `led_to_retry=false`
- Each finding has severity and suggestion fields from review JSON
- Non-satisfied `spec_verification[]` items produce `spec_alignment` findings
- `missing_from_spec[]` items produce `spec_alignment` findings
- `out_of_scope[]` items produce `scope` findings
- `strengths[]` strings produce strength findings (weight 0.5)

---

### Step 3: Guardian Verdicts

**Goal:** Capture how the Product Guardian evaluated each task against the project's vision document. Extract verdicts, scope violations, flags, and persona grounding failures so synthesis can learn which kinds of work tend to drift from the product vision.

**Source data:**

| Artifact | Path | What it provides |
|----------|------|------------------|
| Guardian JSON (primary) | `.speed/features/<name>/logs/guardian-*.json` | `status`, `behavioral_test`, `scope_violations[]`, `persona_grounding[]`, `differentiation_impact`, `flags[]`, `summary` |
| Task JSON `review_feedback` (fallback) | `.speed/features/<name>/tasks/<id>.json` | `"GUARDIAN REJECTED: <summary>"` prefix when guardian rejected at `review.sh:292` |

Guardian files are written at three checkpoints:

| Checkpoint | Filename pattern | Scope |
|------------|-----------------|-------|
| Pre-plan | `guardian-pre-plan-{epoch}.json` | Feature-level: "Should this be built?" |
| Post-review | `guardian-post-review-{epoch}.json` | Per-task: "Did implementation stay true to spec?" |
| Post-integration | `guardian-post-integration-{epoch}.json` | Feature-level: "Does integrated result still align?" |

`_prune_logs()` retains only the 3 most recent files per check type. For typical features (4-6 tasks), all files survive. For 8+ tasks, early post-review files are pruned. The task JSON fallback captures rejections only; aligned and flagged verdicts for pruned files are unrecoverable.

**Solution:**

The function reads guardian JSON files as the primary source, then falls back to task JSON for pruned cases.

**Task ID mapping:** Pre-plan and post-integration guardians are feature-level (`task_id="*"`). Post-review guardians map to specific tasks via `_resolve_task_id()`, which correlates the guardian file's epoch suffix against each task's `reviewed_at` or `completed_at` ISO timestamp (set by `task_set_reviewed()` and task completion in `lib/tasks.sh`). Falls back to `"*"` if no match is found.

**Observation subtypes:** All observations use `obs_type="guardian_verdict"` (the product spec's type list) with a `"subtype"` key in detail for downstream filtering:

| Subtype | Produced when | Weight |
|---------|--------------|--------|
| `verdict` | Non-aligned status (flagged/rejected/misaligned) | 1.0 (explicit) |
| `scope_violation` | `scope_violations[]` entry in a non-aligned file | 2.0 |
| `flag` | Warning or critical entry in `flags[]` | 1.5 |
| `persona_not_served` | `persona_grounding[].served == false` in a non-aligned file | 1.0 |

Weight hierarchy stays below `human_override` (2.5), which the human corrections spec defines as the highest-authority signal. All weights are passed explicitly to `_make_obs()` because `_WEIGHTS["guardian_verdict"]` is 2.0 (the pre-subtype default); without explicit weights, all sub-observations would inherit 2.0. Aligned guardians produce no observations — persona data inside aligned files is not extracted because the guardian already weighed it and determined the feature is fine overall.

**Fallback path:** When guardian files are pruned, the task JSON fallback fires for rejections only. If `review_feedback` starts with `"GUARDIAN REJECTED"` and the task's status is `"done"`, both a `guardian_verdict` and a `human_override` observation are produced (the operator proceeded past the rejection).

```python
def _step3_guardian_verdicts(feature: str, logs_dir: Path,
                              tasks: dict[str, dict],
                              result: ExtractResult) -> None:
    """Step 3: Extract guardian verdicts from guardian JSON files and task JSON."""

    # Primary source: guardian JSON files
    for gfile in sorted(logs_dir.glob("guardian-*.json")):
        data = _read_json(gfile)
        if not isinstance(data, dict):
            continue

        status = data.get("status", "unknown")
        check_type = _parse_check_type(gfile.name)
        task_id = _resolve_task_id(gfile, check_type, tasks) if check_type == "post-review" else "*"

        # Only produce observations for non-aligned verdicts
        if status in ("flagged", "rejected", "misaligned"):
            behavioral = data.get("behavioral_test", {})
            scope_violations = data.get("scope_violations", [])
            flags = data.get("flags", [])
            diff_impact = data.get("differentiation_impact", {})

            detail = {
                "subtype": "verdict",
                "verdict": status,
                "summary": data.get("summary", ""),
                "behavioral_test": behavioral.get("verdict", ""),
                "behavioral_reasoning": behavioral.get("reasoning", ""),
                "scope_violation_count": len(scope_violations),
                "flag_count": len(flags),
                "differentiation_direction": diff_impact.get("direction", ""),
                "check_type": check_type,
                "source_file": gfile.name,
            }
            result.observations.append(
                _make_obs(feature, "guardian", task_id,
                          "guardian_verdict", detail, weight=1.0)
            )

            for sv in scope_violations:
                if not isinstance(sv, dict):
                    continue
                sv_detail = {
                    "subtype": "scope_violation",
                    "feature_name": sv.get("feature", ""),
                    "maps_to": sv.get("maps_to", ""),
                    "severity": sv.get("severity", ""),
                    "reasoning": sv.get("reasoning", ""),
                    "source_file": gfile.name,
                }
                result.observations.append(
                    _make_obs(feature, "guardian", task_id,
                              "guardian_verdict", sv_detail, weight=2.0)
                )

            for flag in flags:
                if not isinstance(flag, dict):
                    continue
                if flag.get("severity") not in ("warning", "critical"):
                    continue
                flag_detail = {
                    "subtype": "flag",
                    "severity": flag.get("severity", ""),
                    "description": flag.get("description", ""),
                    "vision_reference": flag.get("vision_reference", ""),
                    "recommendation": flag.get("recommendation", ""),
                    "source_file": gfile.name,
                }
                result.observations.append(
                    _make_obs(feature, "guardian", task_id,
                              "guardian_verdict", flag_detail, weight=1.5)
                )

            for pg in data.get("persona_grounding", []):
                if not isinstance(pg, dict):
                    continue
                if pg.get("served") is False:
                    pg_detail = {
                        "subtype": "persona_not_served",
                        "persona": pg.get("persona", ""),
                        "use_case": pg.get("use_case", ""),
                        "source_file": gfile.name,
                    }
                    result.observations.append(
                        _make_obs(feature, "guardian", task_id,
                                  "guardian_verdict", pg_detail, weight=1.0)
                    )

    # Secondary source: task JSON prefix check (for pruned guardian files)
    for task_id, task in tasks.items():
        feedback = task.get("review_feedback", "")
        if not isinstance(feedback, str):
            continue
        if not feedback.startswith("GUARDIAN REJECTED"):
            continue
        summary = feedback.replace("GUARDIAN REJECTED: ", "", 1).replace(
            "GUARDIAN REJECTED:", "", 1).strip()
        detail = {
            "subtype": "verdict",
            "verdict": "rejected",
            "summary": summary,
            "task_final_status": task.get("status", "unknown"),
            "led_to_rerun": task.get("status") == "done",
            "source_file": "task_json",
        }
        result.observations.append(
            _make_obs(feature, "guardian", task_id,
                      "guardian_verdict", detail, weight=1.0)
        )

        if task.get("status") == "done":
            override_detail = {
                "original_rejection": feedback,
                "task_status": "done",
                "review_verdict": task.get("review_verdict", "unknown"),
                "retry_count": task.get("retry_count", 0),
            }
            result.observations.append(
                _make_obs(feature, "human", task_id,
                          "human_override", override_detail)
            )
```

Helpers:

```python
def _parse_check_type(filename: str) -> str:
    """Extract checkpoint type from guardian filename.

    guardian-pre-plan-1772438901.json     -> "pre-plan"
    guardian-post-review-1772439353.json  -> "post-review"
    guardian-post-integration-1772439500.json -> "post-integration"
    """
    stem = filename.replace("guardian-", "").rsplit("-", 1)[0]
    return stem


def _resolve_task_id(gfile: Path, check_type: str,
                     tasks: dict[str, dict]) -> str:
    """Map a post-review guardian file to its task ID.

    Guardian filenames use epoch seconds: guardian-post-review-1772439353.json.
    Task JSON stores ISO timestamps: reviewed_at, completed_at (set by
    task_set_reviewed() and task completion in lib/tasks.sh).

    Correlates the guardian epoch with the nearest task reviewed_at or
    completed_at timestamp. Returns "*" if no match.
    """
    try:
        guardian_epoch = int(gfile.stem.rsplit("-", 1)[-1])
    except (ValueError, IndexError):
        return "*"

    best_task = "*"
    best_delta = float("inf")
    for task_id, task in tasks.items():
        # Task JSON has ISO strings: reviewed_at, completed_at
        iso_ts = task.get("reviewed_at") or task.get("completed_at")
        if not iso_ts:
            continue
        try:
            task_epoch = datetime.fromisoformat(
                iso_ts.replace("Z", "+00:00")).timestamp()
        except (ValueError, AttributeError):
            continue
        delta = abs(task_epoch - guardian_epoch)
        if delta < best_delta:
            best_delta = delta
            best_task = task_id
    return best_task
```

**Observation types produced:**

| Type | Stage | Weight | When produced |
|------|-------|--------|---------------|
| `guardian_verdict` (subtype: verdict) | guardian | 1.0 | Non-aligned guardian JSON file, or `"GUARDIAN REJECTED"` in task JSON |
| `guardian_verdict` (subtype: scope_violation) | guardian | 2.0 | Entry in `scope_violations[]` of a non-aligned file |
| `guardian_verdict` (subtype: flag) | guardian | 1.5 | Warning or critical entry in `flags[]` |
| `guardian_verdict` (subtype: persona_not_served) | guardian | 1.0 | `persona_grounding[].served == false` in a non-aligned file |
| `human_override` | human | 2.5 | Task JSON fallback: `"GUARDIAN REJECTED"` + `status == "done"` |

**Known limitations:**

- **Pruning for large features.** For 8+ tasks, early post-review guardian files are pruned. Only rejections are recoverable via task JSON fallback. Flagged verdicts, scope violations, and persona data from pruned files are lost.
- **Skipped detection not implemented.** When a guardian checkpoint was expected but no file exists (e.g., pipeline interruption), that absence is not detected. Requires pipeline stage tracking, flagged for follow-up.
- **Task ID mapping is best-effort.** `_resolve_task_id` correlates guardian epoch timestamps with task `reviewed_at`/`completed_at` ISO timestamps. If neither field is set (e.g., task is still pending), the guardian observation falls back to `task_id="*"`.
- **Reviewer overwrites guardian rejection.** If a task is later reviewer-rejected, `task_request_changes` overwrites `review_feedback` with review JSON, erasing the guardian rejection. The task JSON fallback cannot recover it.

**Test expectations:**

- Guardian JSON with non-aligned status (flagged/rejected/misaligned) produces `guardian_verdict` (subtype: verdict) + scope_violation/flag/persona_not_served sub-observations
- Guardian JSON with status `"aligned"` produces no observations (persona data inside aligned files is not extracted)
- Post-review guardian files map to specific task_ids via timestamp correlation; pre-plan and post-integration use `task_id="*"`
- All `guardian_verdict` observations carry a `subtype` key: `"verdict"`, `"scope_violation"`, `"flag"`, or `"persona_not_served"`
- Weight hierarchy: scope_violation=2.0, flag=1.5, persona_not_served=1.0, verdict=1.0 (all explicit, overriding `_WEIGHTS["guardian_verdict"]=2.0`)
- Fallback: task JSON `review_feedback` starting `"GUARDIAN REJECTED:"` produces `guardian_verdict` (subtype: verdict)
- Fallback: `"GUARDIAN REJECTED"` + `status=done` produces both `guardian_verdict` and `human_override`
- Missing guardian files when expected: not detected (flagged for follow-up)

---

### Step 4 — Verify Findings

**Goal:** Extract actionable findings from the plan verifier's output so the learning system captures spec drift, contract gaps, and verifier recommendations that predict real implementation bugs.

**Source data:**

| Source | Path | Format |
|--------|------|--------|
| Plan verification log | `logs/plan-verification.log` | Markdown-wrapped JSON, pre-parsed by bash bridge via `parse_agent_json` into a temp file passed as `verify_json_path` |

The verifier JSON contains five arrays:

| Array | What it contains | Currently extracted? |
|-------|-----------------|---------------------|
| `spec_requirements[]` | Each requirement with status `covered`, `partial`, `missing`, or `drifted` | Only `drifted` and `missing` |
| `critical_failures[]` | Blocking failures that should halt the pipeline | Yes |
| `semantic_drift[]` | Terminology or intent mismatches between spec and plan | Yes (mapped to `finding_type: "spec_drift"`) |
| `recommendations[]` | Verifier suggestions that often predict real bugs | No |
| `contract_issues[]` | Missing functions, undeclared dependencies between tasks | No |

**What's missing and why it matters:**

1. **`recommendations[]`** — In the real `speed-defects` verification, 6 recommendations were produced. Three predicted actual implementation problems: template duplication (recommendation 1), missing backward transitions (recommendation 2), and underspecified log files (recommendation 3). Capturing these as observations lets the synthesis step learn which verifier recommendations correlate with downstream failures.

2. **`contract_issues[]`** — The same verification produced 2 contract issues: undeclared functions `get_defect_dir`, `set_defect_branch`, and `defect_name_from_path`. Contract issues indicate the plan's inter-task wiring is incomplete. If a task calls a function that no task declares, that surfaces as an integration bug later. Weight 1.5 reflects higher signal than a generic recommendation.

3. **`partial` requirements** — Requirements with `status: "partial"` sit between covered and missing. The real data has one: "Triage correctly identifies root cause files in >80% of cases" with `uncertain: true` and a note explaining there's no measurement mechanism. Partial requirements with `uncertain: true` are especially valuable because they flag spec ambiguity the plan couldn't resolve.

**Solution:**

Extend `_step4_verify_findings` with three additions:

```python
# 1. Include partial requirements (currently only drifted/missing)
if status in ("drifted", "missing", "partial"):
    detail = {
        "finding_type": "partial_requirement" if status == "partial" else "spec_drift" if status == "drifted" else "missing_requirement",
        "requirement": req.get("requirement", req.get("spec_quote", "")),
        "status": status,
        "spec_location": req.get("spec_section", ""),
        "analysis": req.get("notes", req.get("evidence", "")),
        "uncertain": req.get("uncertain", False),
    }
    result.observations.append(
        _make_obs(feature, "verifier", "*", "verify_finding", detail,
                  weight=1.0 if status == "partial" else None)
    )

# 2. Extract recommendations
for rec in data.get("recommendations", []):
    if not isinstance(rec, str):
        continue
    detail = {
        "finding_type": "recommendation",
        "requirement": rec,
        "status": "suggested",
        "spec_location": "",
        "analysis": "",
    }
    result.observations.append(
        _make_obs(feature, "verifier", "*", "verify_finding", detail,
                  weight=1.0)
    )

# 3. Extract contract_issues
for issue in data.get("contract_issues", []):
    if not isinstance(issue, dict):
        continue
    detail = {
        "finding_type": "contract_issue",
        "requirement": issue.get("description", ""),
        "status": issue.get("type", "unknown"),
        "spec_location": "",
        "analysis": "",
    }
    result.observations.append(
        _make_obs(feature, "verifier", "*", "verify_finding", detail,
                  weight=1.5)
    )
```

**Weight rationale:**

| Finding type | Weight | Why |
|-------------|--------|-----|
| `spec_drift` (drifted requirement) | 2.0 | Inherits from `_WEIGHTS["verify_finding"]`, no explicit override needed |
| `missing_requirement` | 2.0 | Same — missing is as serious as drifted |
| `critical_failure` | 2.0 | Same — these are blocking |
| `partial_requirement` | 1.0 | Explicit override. Lower than drift/missing because the plan partially addresses it |
| `recommendation` | 1.0 | Explicit override. Suggestions, not failures. Signal value emerges when correlated with downstream outcomes in synthesis |
| `contract_issue` | 1.5 | Explicit override. Higher than recommendations because they indicate concrete inter-task wiring gaps |

Like Step 3, `spec_drift`, `missing_requirement`, and `critical_failure` do not pass an explicit weight, so they inherit `_WEIGHTS["verify_finding"] = 2.0`. The three new types pass explicit weights to override that default.

**Observation type schema:**

All Step 4 observations use type `verify_finding`. The `finding_type` field inside `detail` differentiates them:

```json
{
  "id": "<sha256>",
  "feature": "speed-defects",
  "source": "verifier",
  "task_id": "*",
  "type": "verify_finding",
  "detail": {
    "finding_type": "recommendation | contract_issue | partial_requirement | spec_drift | missing_requirement | critical_failure",
    "requirement": "...",
    "status": "suggested | missing_function | partial | drifted | missing | failed",
    "spec_location": "...",
    "analysis": "...",
    "uncertain": false
  },
  "weight": 1.0
}
```

The `uncertain` field only appears on `partial_requirement` findings. For all other types it defaults to `false`.

**Known limitations:**

- **All observations use `task_id="*"`.** The verifier evaluates the plan as a whole, not individual tasks. Requirements map to tasks via `mapped_to_task` in the JSON, but that field is a comma-separated string (e.g., `"3, 6, 9"`), not a single task ID. Splitting into per-task observations would create duplicate findings. The feature-level `"*"` is correct here.
- **Recommendations are unstructured strings.** Unlike requirements and contract issues (which are dicts with typed fields), recommendations are plain strings. The `detail` schema stores the full string in `requirement` with `status: "suggested"`. Downstream correlation with actual bugs requires fuzzy matching in synthesis.
- **`covered` requirements are ignored.** A requirement with `status: "covered"` produces no observation. Covered requirements could feed `success` observations in a future step, but that's outside Step 4's scope.
- **Verifier output is per-feature, not per-run.** The bridge reads `logs/plan-verification.log`, which is overwritten on each plan verification run. Only the most recent verification is captured.

**Test expectations:**

- `spec_requirements` with `status: "drifted"` → `verify_finding` with `finding_type: "spec_drift"`, weight 2.0
- `spec_requirements` with `status: "missing"` → `verify_finding` with `finding_type: "missing_requirement"`, weight 2.0
- `spec_requirements` with `status: "partial"` → `verify_finding` with `finding_type: "partial_requirement"`, weight 1.0
- `spec_requirements` with `status: "partial"` and `uncertain: true` → `detail["uncertain"]` is `True`
- `spec_requirements` with `status: "covered"` → no observation
- `critical_failures[]` (string or dict) → `verify_finding` with `finding_type: "critical_failure"`, weight 2.0
- `semantic_drift[]` → `verify_finding` with `finding_type: "spec_drift"`, weight 2.0
- `recommendations[]` (strings) → `verify_finding` with `finding_type: "recommendation"`, weight 1.0
- `contract_issues[]` (dicts) → `verify_finding` with `finding_type: "contract_issue"`, weight 1.5
- Empty verifier JSON → warning, no observations
- Missing `verify_json_path` → warning, no observations
- All observations have `task_id="*"` and `source="verifier"`

---

### Step 5 — Coherence Issues

**Goal:** Extract cross-task composition failures from the coherence checker so the learning system captures interface mismatches, schema inconsistencies, missing wiring, contract gaps, and duplicates that surface only when independently-developed task branches are combined.

**Source data:**

| Source | Path | Format |
|--------|------|--------|
| Coherence log | `logs/coherence.log` | Raw JSON or markdown-wrapped JSON, pre-parsed by bash bridge via `parse_agent_json` into a temp file passed as `coherence_json_path` |

The coherence checker agent (agents/coherence-checker.md, line 75) requires raw JSON output with 7 arrays. In practice, the agent sometimes produces markdown instead (speed-security's coherence.log is pure markdown with tables, no JSON). When that happens, the bash bridge's `parse_agent_json` yields an empty string, the temp file is empty, and Step 5 sees "Empty or invalid coherence JSON."

The agent's JSON schema defines these arrays:

| Array | What it contains | Currently extracted? |
|-------|-----------------|---------------------|
| `interface_mismatches[]` | Signature/type/import mismatches between tasks | Yes |
| `schema_inconsistencies[]` | Model/field/enum disagreements across tasks | Yes |
| `missing_connections[]` | Unregistered models, unwired routes, missing imports | Yes |
| `critical_issues[]` | Strings describing blocking composition failures | No |
| `contract_gaps[]` | Contract item satisfaction status (satisfied/missing/partial) | No |
| `duplicates[]` | Same function/model/test implemented by multiple tasks | No |
| `recommendations[]` | Suggested fixes from the coherence checker | No |

**What's missing and why it matters:**

1. **`critical_issues[]`** — These are the coherence checker's highest-severity findings: "Task 4 missing entirely," "Task 12 missing entirely," "`grep -oP` on macOS." In the speed-security data, 3 critical issues were produced. They directly identify integration blockers. Weight 2.5 matches their severity (higher than the default 2.0 for a standard coherence issue).

2. **`contract_gaps[]`** — Each gap has a `status` field: `satisfied`, `missing`, or `partial`. Satisfied gaps are noise (analogous to covered requirements in Step 4). Missing and partial gaps indicate the combined code doesn't fulfill the architect's contract. In f9-profile-completeness, all 8 gaps are satisfied. In features with composition problems, missing/partial gaps would pinpoint exactly which contract items broke.

3. **`duplicates[]`** — Two tasks implementing the same utility or model independently. Duplicates waste effort and create maintenance confusion about which copy is canonical. f9-profile-completeness has none, but this is a real risk in features with 8+ tasks where isolation increases.

4. **`recommendations[]`** — Coherence-checker suggestions for fixes. f9-profile-completeness has 1 recommendation about renaming a test mock field. Lower weight (1.0) since these are suggestions, not failures.

**Problem 2: Markdown fallback.** Speed-security's coherence.log is pure markdown. The agent violated its output format instruction. The fix is not to parse arbitrary markdown (brittle and unbounded) but to extract the status and count the findings from the structured markdown sections when JSON parsing fails. A `_parse_coherence_markdown` fallback can pull `status: pass|fail`, count critical/major/minor issues from the table rows, and emit a single summary observation so the feature isn't silently invisible.

**Solution:**

Two changes: (a) extract 4 missing arrays from the JSON path, (b) add a markdown fallback for non-JSON output.

```python
def _step5_coherence_issues(feature: str, coherence_json_path: Path | None,
                            result: ExtractResult) -> None:
    """Step 5: Extract coherence issues from pre-parsed coherence JSON."""
    if not coherence_json_path or not coherence_json_path.exists():
        result.warnings.append("No coherence data available")
        return

    data = _read_json(coherence_json_path)
    if not isinstance(data, dict):
        # Try markdown fallback
        raw = coherence_json_path.read_text().strip()
        if raw:
            _step5_coherence_markdown_fallback(feature, raw, result)
        else:
            result.warnings.append("Empty or invalid coherence JSON")
        return

    # ── Existing 3 arrays (interface_mismatches, schema_inconsistencies,
    #    missing_connections) ──
    issue_sources = [
        ("interface_mismatches", "interface_mismatch"),
        ("schema_inconsistencies", "schema_inconsistency"),
        ("missing_connections", "missing_connection"),
    ]

    for json_key, issue_type in issue_sources:
        for item in data.get(json_key, []):
            if not isinstance(item, dict):
                continue
            detail = {
                "issue_type": issue_type,
                "task_a": str(item.get("task_a", ...)),  # existing logic
                "task_b": str(item.get("task_b", ...)),
                "location_a": item.get("location_a", item.get("location", "")),
                "location_b": item.get("location_b", ""),
                "description": item.get("description", item.get("issue", "")),
                "severity": item.get("severity", "warning"),
            }
            result.observations.append(
                _make_obs(feature, "coherence", "*",
                          "coherence_issue", detail)
            )

    # ── New: critical_issues ──
    for issue_text in data.get("critical_issues", []):
        if not isinstance(issue_text, str) or not issue_text.strip():
            continue
        detail = {
            "issue_type": "critical_issue",
            "description": issue_text,
            "severity": "critical",
        }
        result.observations.append(
            _make_obs(feature, "coherence", "*",
                      "coherence_issue", detail, weight=2.5)
        )

    # ── New: contract_gaps (only missing/partial) ──
    for gap in data.get("contract_gaps", []):
        if not isinstance(gap, dict):
            continue
        status = gap.get("status", "")
        if status in ("missing", "partial"):
            detail = {
                "issue_type": "contract_gap",
                "description": gap.get("contract_item", ""),
                "status": status,
                "notes": gap.get("notes", ""),
                "severity": "major" if status == "missing" else "minor",
            }
            result.observations.append(
                _make_obs(feature, "coherence", "*",
                          "coherence_issue", detail, weight=2.0)
            )

    # ── New: duplicates ──
    for dup in data.get("duplicates", []):
        if not isinstance(dup, dict):
            continue
        detail = {
            "issue_type": "duplicate",
            "description": dup.get("description", ""),
            "locations": dup.get("locations", []),
            "severity": "major",
        }
        result.observations.append(
            _make_obs(feature, "coherence", "*",
                      "coherence_issue", detail)
        )

    # ── New: recommendations ──
    for rec in data.get("recommendations", []):
        if not isinstance(rec, str) or not rec.strip():
            continue
        detail = {
            "issue_type": "recommendation",
            "description": rec,
            "severity": "info",
        }
        result.observations.append(
            _make_obs(feature, "coherence", "*",
                      "coherence_issue", detail, weight=1.0)
        )
```

Markdown fallback (new helper):

```python
def _step5_coherence_markdown_fallback(feature: str, raw: str,
                                        result: ExtractResult) -> None:
    """Extract minimal coherence signal from markdown when JSON parse fails."""
    import re

    # Determine pass/fail from the markdown
    status = "unknown"
    if "**Status: FAIL**" in raw or "Verdict: **FAIL**" in raw:
        status = "fail"
    elif "**Status: PASS**" in raw or "Verdict: **PASS**" in raw:
        status = "pass"

    # Count table rows in Critical/Major sections
    critical_count = 0
    major_count = 0
    in_critical = False
    in_major = False
    for line in raw.splitlines():
        if "Critical Issues" in line or "What blocks" in line:
            in_critical = True
            in_major = False
        elif "Major Issues" in line:
            in_major = True
            in_critical = False
        elif line.startswith("###") or (line.startswith("##") and "Issues" not in line):
            in_critical = False
            in_major = False
        elif line.startswith("|") and not line.startswith("| #") and not line.startswith("|--"):
            if in_critical:
                critical_count += 1
            elif in_major:
                major_count += 1

    if status == "unknown" and critical_count == 0 and major_count == 0:
        result.warnings.append("Coherence output is non-JSON and unparseable")
        return

    detail = {
        "issue_type": "markdown_summary",
        "description": (f"Coherence checker produced markdown instead of JSON. "
                        f"Status: {status}, {critical_count} critical, "
                        f"{major_count} major issues detected."),
        "severity": "critical" if status == "fail" else "info",
        "critical_count": critical_count,
        "major_count": major_count,
        "status": status,
    }
    weight = 2.5 if status == "fail" else 1.0
    result.observations.append(
        _make_obs(feature, "coherence", "*",
                  "coherence_issue", detail, weight=weight)
    )
    result.warnings.append(
        "Coherence output was markdown, not JSON. Only summary extracted."
    )
```

**Weight rationale:**

| Issue type | Weight | Why |
|-----------|--------|-----|
| `interface_mismatch` | 2.0 | Inherits from `_WEIGHTS["coherence_issue"]` |
| `schema_inconsistency` | 2.0 | Same |
| `missing_connection` | 2.0 | Same |
| `critical_issue` | 2.5 | Explicit override. Integration blockers are higher severity than standard composition issues |
| `contract_gap` (missing/partial) | 2.0 | Explicit (same as default, but stated for clarity since satisfied gaps are filtered out) |
| `duplicate` | 2.0 | Inherits default |
| `recommendation` | 1.0 | Explicit override. Suggestions, not failures |
| `markdown_summary` (fallback) | 2.5 if fail, 1.0 if pass | Explicit. A failed coherence check with lost detail is high signal |

**Observation type schema:**

All Step 5 observations use type `coherence_issue`. The `issue_type` field inside `detail` differentiates them:

```json
{
  "id": "<sha256>",
  "feature": "speed-security",
  "source": "coherence",
  "task_id": "*",
  "type": "coherence_issue",
  "detail": {
    "issue_type": "interface_mismatch | schema_inconsistency | missing_connection | critical_issue | contract_gap | duplicate | recommendation | markdown_summary",
    "description": "...",
    "severity": "critical | major | minor | info",
    "...": "additional fields vary by issue_type"
  },
  "weight": 2.0
}
```

**Known limitations:**

- **Markdown fallback is lossy.** When the coherence checker produces markdown, only a summary observation is emitted (status + issue counts). Individual findings, file locations, and descriptions are not recovered. The real fix is upstream: ensure the coherence checker consistently outputs JSON. The fallback exists so the feature isn't silently invisible to the learning system.
- **All observations use `task_id="*"`.** Coherence issues span task boundaries by definition. Some arrays include `task_a`/`task_b` fields identifying the involved tasks, but splitting into per-task observations would misrepresent the issue (the bug is in the seam, not in either task).
- **`contract_gaps` with `status: "satisfied"` are ignored.** Satisfied gaps are the equivalent of covered requirements in Step 4 — no signal for learning. Only missing and partial gaps produce observations.
- **`duplicates` may be empty in practice.** Across 5 real features examined (speed-defects, speed-security, f10-rich-feed, f9-profile-completeness, seed-onboarding-flag), no duplicates were found. The extraction path exists for completeness since the agent schema defines the array.

**Test expectations:**

- `interface_mismatches`, `schema_inconsistencies`, `missing_connections` → `coherence_issue` with matching `issue_type`, weight 2.0 (unchanged)
- `critical_issues[]` (strings) → `coherence_issue` with `issue_type: "critical_issue"`, weight 2.5
- `contract_gaps[]` with `status: "missing"` → `coherence_issue` with `issue_type: "contract_gap"`, weight 2.0
- `contract_gaps[]` with `status: "satisfied"` → no observation
- `duplicates[]` (dicts) → `coherence_issue` with `issue_type: "duplicate"`, weight 2.0
- `recommendations[]` (strings) → `coherence_issue` with `issue_type: "recommendation"`, weight 1.0
- Markdown with "Status: FAIL" + 3 critical table rows → `coherence_issue` with `issue_type: "markdown_summary"`, `critical_count: 3`, weight 2.5
- Markdown with "Status: PASS" → `coherence_issue` with `issue_type: "markdown_summary"`, weight 1.0
- Empty coherence JSON → warning, no observations
- Missing `coherence_json_path` → warning, no observations

---

### Step 6 — Security Findings

**Goal:** Extract spec validation findings and security audit findings so the learning system captures architecture concerns, spec-code mismatches, and security vulnerabilities identified during planning and auditing.

**Source data:**

Two files from different pipeline stages, with zero overlap in content:

| Source | Path | Written by | When | Format |
|--------|------|-----------|------|--------|
| Validation report | `logs/validation-report.json` | `lib/cmd/plan.sh:581` | `speed plan` | Top-level JSON array of finding dicts |
| Security audit | `logs/security-audit.json` | `lib/security.sh:377` | `speed security` or security gate | JSON dict with `validation` array inside |

Data availability across 5 real features:

| Feature | validation-report | security-audit | Currently extracted |
|---------|------------------|----------------|-------------------|
| speed-defects | 7 findings | none | 0 |
| speed-security | 11 findings | 6 findings | 6 |
| f10-rich-feed | 5 findings | none | 0 |
| f9-profile-completeness | 4 findings | none | 0 |
| seed-onboarding-flag | 2 findings | none | 0 |

Both files share the same item schema: `issue`, `severity`, `product_requirement`, `recommendation`. Neither file includes `file` or `line` fields (the current code's `finding.get("file", "")` always returns empty).

**Problem:**

The current code reads only `security-audit.json`. That file exists in 1 of 5 features. `validation-report.json` exists in all 5 and is the primary source of findings, but is never read. Result: 6 of 35 findings extracted (17%).

**Solution:**

Read both files. Try `validation-report.json` first (present in all features), then `security-audit.json` (present only when the security auditor runs). Handle both container shapes: bare array (validation-report) and dict with `validation` key (security-audit).

```python
def _step6_security_findings(feature: str, logs_dir: Path,
                               result: ExtractResult) -> None:
    """Step 6: Extract findings from validation-report.json and security-audit.json."""
    all_findings: list[dict] = []

    # Source 1: validation-report.json (from speed plan)
    vr_path = logs_dir / "validation-report.json"
    if vr_path.exists():
        vr_data = _read_json(vr_path)
        if isinstance(vr_data, list):
            all_findings.extend(f for f in vr_data if isinstance(f, dict))
        elif isinstance(vr_data, dict):
            all_findings.extend(
                f for f in vr_data.get("validation", vr_data.get("findings", []))
                if isinstance(f, dict)
            )

    # Source 2: security-audit.json (from speed security / security gate)
    sa_path = logs_dir / "security-audit.json"
    if sa_path.exists():
        sa_data = _read_json(sa_path)
        if isinstance(sa_data, dict):
            all_findings.extend(
                f for f in sa_data.get("validation", sa_data.get("findings", []))
                if isinstance(f, dict)
            )
        elif isinstance(sa_data, list):
            all_findings.extend(f for f in sa_data if isinstance(f, dict))

    if not all_findings:
        if not vr_path.exists() and not sa_path.exists():
            result.warnings.append("No validation-report.json or security-audit.json found")
        else:
            result.warnings.append("Security/validation files exist but contain no findings")
        return

    for i, finding in enumerate(all_findings):
        issue_text = finding.get("issue", "")
        finding_id = f"SEC-{i+1:03d}"
        severity = finding.get("severity", "note")
        title = issue_text

        # Parse "SEC-NNN (severity): Title..." pattern
        sec_match = re.match(r"(SEC-\d+)\s*\((\w+)\):\s*(.*)", issue_text)
        if sec_match:
            finding_id = sec_match.group(1)
            severity = sec_match.group(2)
            title = sec_match.group(3)

        detail = {
            "finding_id": finding_id,
            "severity": severity,
            "title": title[:200] if title else "",
            "recommendation": finding.get("recommendation", ""),
            "product_requirement": finding.get("product_requirement", ""),
        }
        result.observations.append(
            _make_obs(feature, "security", "*",
                      "security_finding", detail)
        )
```

**Changes from current code:**

1. Reads `validation-report.json` (primary) and `security-audit.json` (secondary), not just the latter
2. Handles bare array shape (validation-report) in addition to dict-with-key shape (security-audit)
3. Adds `product_requirement` to detail (present in all findings, was ignored)
4. Removes `file`, `line`, `category` from detail (always empty in real data)
5. Warning message reflects both filenames

**Weight:** All findings inherit `_WEIGHTS["security_finding"] = 1.5`. No explicit overrides needed — severity differentiation is captured in `detail["severity"]` for downstream consumers.

**Observation type schema:**

```json
{
  "id": "<sha256>",
  "feature": "speed-defects",
  "source": "security",
  "task_id": "*",
  "type": "security_finding",
  "detail": {
    "finding_id": "SEC-001",
    "severity": "warning | note | critical | medium",
    "title": "...",
    "recommendation": "...",
    "product_requirement": "..."
  },
  "weight": 1.5
}
```

**Known limitations:**

- **No deduplication between files.** If a finding somehow appears in both `validation-report.json` and `security-audit.json`, it produces two observations. In practice, the two files have zero overlap across all 5 examined features (different pipeline stages, different agents, different content).
- **All observations use `task_id="*"`.** Validation findings are about the plan as a whole; security findings are about the codebase. Neither is task-scoped.
- **`file` and `line` are not extracted.** Neither file type includes these fields in practice. If future security audit output includes them, the schema can be extended.
- **Severity values are not normalized.** `validation-report.json` uses `warning`/`note`. `security-audit.json` uses SEC-prefixed patterns with `medium`/`high`. Both are preserved as-is in the detail.

**Test expectations:**

- `validation-report.json` (bare array) → `security_finding` per item, weight 1.5
- `security-audit.json` (dict with `validation` key) → `security_finding` per item, weight 1.5
- Both files present → findings from both are extracted (no dedup)
- SEC-NNN pattern in issue text → `finding_id` and `severity` parsed from it
- `product_requirement` field preserved in detail
- Neither file exists → warning, no observations
- Files exist but empty arrays → warning, no observations
- All observations have `task_id="*"` and `source="security"`

---

### Step 7 — Context Effectiveness

**Goal:** Measure whether the pre-computed context package (code-context.json) predicted what the developer actually needed. Files the developer touched but context missed are learning signals for the context engine. Files context provided but the developer never needed indicate wasted tokens.

**Source data:**

| Source | Path | Written by | Content |
|--------|------|-----------|---------|
| Context package | `.speed/context/tasks/{id}/context/code-context.json` | `lib/context/code_context.py` | Three tiers of files provided to the developer agent |
| Task outcome | `{feature_dir}/tasks/{id}.json` | Step 1 | `files_touched` array from git diff |

The context package organizes files into three tiers:

| Tier | JSON path | Content level | Purpose |
|------|-----------|--------------|---------|
| Seed files | `full_content.files_touched[]` | Full source | Task's declared files |
| One-hop | `full_content.one_hop{}` | Full source | Direct imports/callers of seed files |
| Two-hop | `skeleton.two_hop[]` | Skeleton only | Neighbors of one-hop files |

All three tiers contribute to the "provided files" set for comparison against `files_touched`.

**Problem:** The current code is a no-op. It logs a warning about `code-context.json` not persisting and returns. The files do persist at the global path (`.speed/context/tasks/{id}/...`) but are not feature-scoped. Task IDs from different features collide: running feature B overwrites feature A's task 1 context. When `speed learn` runs immediately after `speed run`, the files are still valid because no other feature has overwritten them.

**Solution:**

```python
def _step7_context_effectiveness(feature: str, tasks: dict[str, dict],
                                  context_base: Path | None,
                                  result: ExtractResult) -> None:
    if not context_base or not context_base.exists():
        result.warnings.append(
            "Context effectiveness skipped: no context directory found"
        )
        return

    any_found = False
    for task_id, task in tasks.items():
        actual = set(task.get("files_touched", []))
        if not actual:
            continue

        cc_path = context_base / task_id / "context" / "code-context.json"
        if not cc_path.exists():
            continue
        cc = _read_json(cc_path)
        if not isinstance(cc, dict):
            continue

        any_found = True
        provided = set()
        tiers = {}  # file -> tier name

        fc = cc.get("full_content", {})
        if isinstance(fc, dict):
            for f in fc.get("files_touched", []):
                p = f.get("path", "") if isinstance(f, dict) else str(f)
                if p:
                    provided.add(p)
                    tiers[p] = "seed"
            oh = fc.get("one_hop", {})
            if isinstance(oh, dict):
                for p in oh:
                    provided.add(p)
                    tiers[p] = "one_hop"
            elif isinstance(oh, list):
                for f in oh:
                    p = f.get("path", "") if isinstance(f, dict) else str(f)
                    if p:
                        provided.add(p)
                        tiers[p] = "one_hop"

        sk = cc.get("skeleton", {})
        if isinstance(sk, dict):
            for tier_val in sk.values():
                if isinstance(tier_val, list):
                    for f in tier_val:
                        p = f.get("path", "") if isinstance(f, dict) else str(f)
                        if p:
                            provided.add(p)
                            tiers[p] = "skeleton"
                elif isinstance(tier_val, dict):
                    for p in tier_val:
                        provided.add(p)
                        tiers[p] = "skeleton"

        if not provided:
            continue

        misses = actual - provided
        for f in sorted(misses):
            result.observations.append(
                _make_obs(feature, "context", task_id, "context_miss", {
                    "file": f,
                    "reason": "Modified by developer but not in context package",
                    "task_files_declared": sorted(provided & actual),
                })
            )

        waste_files = provided - actual
        waste_ratio = len(waste_files) / len(provided) if provided else 0
        summary = cc.get("expansion_summary", {})
        if waste_ratio > 0.9 and len(provided) > 5:
            result.observations.append(
                _make_obs(feature, "context", task_id, "context_waste", {
                    "waste_ratio": round(waste_ratio, 2),
                    "provided_count": len(provided),
                    "used_count": len(provided) - len(waste_files),
                    "total_tokens_estimate": summary.get("total_tokens_estimate", 0),
                    "reason": f"{len(waste_files)} of {len(provided)} context files unused",
                })
            )

    if not any_found:
        result.warnings.append(
            "Context effectiveness skipped: no code-context.json files found for any task"
        )
```

The caller passes `context_base = feature_dir.parent.parent / "context" / "tasks"` (resolving to `.speed/context/tasks/`).

**Weight rationale:**

| Type | Weight | Rationale |
|------|--------|-----------|
| `context_miss` | 1.5 | Developer needed a file that context didn't provide. Signal for improving the context engine's expansion. |
| `context_waste` | 0.5 | Context over-provisioned. Low weight because broad context is a deliberate design choice, not a defect. Only emitted when waste exceeds 90% with >5 files provided. |

**Observation schemas:**

`context_miss`:
```json
{
  "file": "src/frontend/src/app/profile/[username]/profile-content.test.tsx",
  "reason": "Modified by developer but not in context package",
  "task_files_declared": ["src/frontend/src/app/profile/[username]/page.tsx"]
}
```

`context_waste`:
```json
{
  "waste_ratio": 0.98,
  "provided_count": 46,
  "used_count": 1,
  "total_tokens_estimate": 97000,
  "reason": "45 of 46 context files unused"
}
```

**Known limitations:**

- **Global path, not feature-scoped.** Context files at `.speed/context/tasks/{id}/...` are overwritten when the next feature runs. Extraction is only reliable when `speed learn` runs immediately after `speed run`. A stale-data warning would require tracking file modification times vs feature start time, which is deferred.
- **New files are always misses.** If the developer creates a new file (e.g., a test file), it can't be in the context package because it didn't exist. These are valid signals (the context engine could predict that test files will be created) but they inflate the miss count. No filtering for now.
- **No token-level waste for individual files.** The spec schema includes `tokens_consumed` per waste file. The context package has `total_tokens_estimate` in `expansion_summary` but not per-file token counts. Only the aggregate is available.
- **Projects without context files skip silently.** The speed project has no `.speed/context/tasks/` directory. Step 7 warns and produces no observations, same as before.

**Test expectations:**

- Task touches 2 files, context provides 46 files including 1 of the 2 touched → 1 `context_miss` (the uncovered file) + 1 `context_waste` (98% waste with 46 files)
- Task touches 2 files, context provides 3 files including both touched → 0 `context_miss`, 0 `context_waste` (waste ratio 33%, below 90% threshold)
- Task with no `files_touched` → skipped, no observations
- Task with no `code-context.json` → skipped, no observations
- No context directory at all → warning, no observations
- All observations use `stage="context"` and per-task `task_id`
- `context_miss` weight 1.5, `context_waste` weight 0.5 (from `_WEIGHTS`)

---

### Step 8 — Decomposition Quality

**Goal:** Compare the files each task was *planned* to touch (from the Architect's decomposition) against the files each task *actually* touched (from git diff). Mismatches reveal tasks that leaked across boundaries, missed dependencies, or were scoped too broadly.

**Source data:**

| Source | Path | Content |
|--------|------|---------|
| Architect plan | `logs/Architect-{timestamp}.jsonl`, last line, `structured_output.tasks[]` | Planned `files_touched` per task |
| Task outcome | `{feature_dir}/tasks/{id}.json` | Actual `files_touched` from git diff (loaded by Step 1) |

The Architect JSONL is a multi-line log. The last line has `type: "result"` with a `structured_output` field containing the full task decomposition. Each task object has `id` and `files_touched` (the Architect's prediction of which files the developer will modify).

**Data availability across features:**

| Feature | Architect JSONL | Tasks | Plan matches actual |
|---------|----------------|-------|-------------------|
| speed-defects | 3 files (use newest) | 12 (1-9, 10a-c) | Tasks 1-9 match. 10a/10b/10c are sub-tasks not in plan (skipped). |
| speed-security | none | — | Step 8 skips (warning) |
| f10-rich-feed | 1 file | 4 | All 4 match exactly |
| f9-profile-completeness | 1 file | 7 | All 7 match exactly |
| seed-onboarding-flag | 1 file | 1 | Match |

Across 24 tasks with Architect plans, every task's actual files match the planned files exactly. The decomposition quality is perfect in the current dataset, so Step 8 produces zero `decomposition_miss` observations. This is the correct outcome: the step is working when there are no mismatches to report.

**Problem:** The plan is loaded from `security-audit.json` (line 1464 in extract.py), which contains security findings, not the Architect's task plan. `plan` is either `None` (file doesn't exist) or the wrong shape (no `tasks` array with `files_touched`). Step 8 silently returns at line 1267 and never runs the comparison.

**Solution:**

New helper to load the plan from the correct file:

```python
def _load_architect_plan(logs_dir: Path) -> dict | None:
    """Load the plan from the Architect agent's JSONL output."""
    architect_files = sorted(logs_dir.glob("Architect-*.jsonl"))
    if not architect_files:
        return None
    try:
        with open(architect_files[-1], "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
        if not lines:
            return None
        last = json.loads(lines[-1])
        so = last.get("structured_output")
        return so if isinstance(so, dict) else None
    except (json.JSONDecodeError, OSError):
        return None
```

Replace the caller (line 1463-1465):

```python
plan = _load_architect_plan(logs_dir)
```

Add a warning when no plan is found (inside `_step8_decomposition_quality`):

```python
if not plan or not isinstance(plan, dict):
    result.warnings.append(
        "Decomposition quality skipped: no Architect plan found"
    )
    return
```

The comparison logic (lines 1270-1310) is unchanged. It correctly classifies mismatches as `scope_too_broad` (extras > 50% of planned), `missing_dependency` (missing but no extras), or `boundary_mismatch` (both extras and missing).

**Observation type:**

`decomposition_miss` (weight 2.0):
```json
{
  "issue": "scope_too_broad",
  "planned_files": ["src/api/auth.py", "src/api/auth_test.py"],
  "actual_files": ["src/api/auth.py", "src/api/auth_test.py", "src/db/users.py", "src/db/migrations/003.py"],
  "analysis": "Task touched 4 files instead of planned 2. Extras: ['src/db/migrations/003.py', 'src/db/users.py']. Missing: []."
}
```

Issue classification:

| Issue | Condition | Meaning |
|-------|-----------|---------|
| `scope_too_broad` | extras > 50% of planned count | Developer touched significantly more files than planned |
| `missing_dependency` | missing files but no extras | Developer didn't touch files they were supposed to |
| `boundary_mismatch` | both extras and missing | Some planned files skipped, other files touched instead |

**Known limitations:**

- **Sub-tasks not in plan are skipped.** Tasks like 10a/10b/10c (split from task 10 during execution) have no plan entry. No comparison is possible, and no warning is emitted. This is correct behavior: the Architect planned task 10, the Supervisor split it.
- **Multiple Architect JSONL files.** When multiple exist (retries), the newest is used. Older plans from failed runs are ignored.
- **Perfect match = zero observations.** Across all current data, planned and actual files are identical. Step 8 will produce observations only when tasks deviate from their plan.

**Test expectations:**

- Task planned `[a.py]`, actual `[a.py, b.py, c.py]` → `decomposition_miss` with `issue: "scope_too_broad"`, weight 2.0
- Task planned `[a.py, b.py]`, actual `[a.py]` → `decomposition_miss` with `issue: "missing_dependency"`
- Task planned `[a.py]`, actual `[b.py]` → `decomposition_miss` with `issue: "boundary_mismatch"`
- Task planned and actual match exactly → no observation
- Task not in plan → skipped, no observation
- No Architect JSONL → warning, no observations
- All observations use `stage="architect"` and per-task `task_id`
- Real data (speed-defects, f10-rich-feed, f9-profile-completeness, seed-onboarding-flag): zero `decomposition_miss` observations (all plans match)

---

### Step 9 — Success Observations

**Goal:** Record a `success` observation for every task that completed without genuine issues. Success observations are the positive signal in the learning system: they tell synthesis which tasks, models, and file scopes worked well, so those patterns can be reinforced.

**Source data:**

| Source | Content | Used for |
|--------|---------|----------|
| `result.observations` (Steps 1-8) | All observations emitted so far | Determining which tasks had blocking issues |
| Task JSON (`tasks/{id}.json`) | `status`, `agent_model`, `files_touched`, timestamps | Success detail fields |
| Architect plan (from `_load_architect_plan`) | `files_touched` per task | Real `files_planned` count |

**Problem 1: Blocking logic is too aggressive.** The current `task_issues` set includes *any* non-success observation with a task ID. Nit-level reviewer findings, positive reviewer feedback, agent self-reported concerns, context misses, and decomposition misses all block a task from getting a success observation. Result: zero success observations across all features in both projects.

Only these observation types represent genuine task-level failures:

| Blocks success | Observation type | Condition |
|----------------|-----------------|-----------|
| Yes | `retry` | Always (task failed and was re-run) |
| Yes | `gate_failure` | Always (lint/test/typecheck failed) |
| Yes | `guardian_verdict` | Always (guardian flagged/rejected the task) |
| Yes | `reviewer_finding` | Only when severity is not `nit` or `positive` |
| No | `agent_concern` | Informational self-report, not a failure |
| No | `context_miss` | Context engine problem, not developer quality |
| No | `context_waste` | Context engine problem, not developer quality |
| No | `decomposition_miss` | Architect problem, not developer quality |

Fixed blocking logic:

```python
_NON_BLOCKING_TYPES = frozenset({
    "agent_concern", "context_miss", "context_waste",
    "decomposition_miss", "success",
})

task_issues: set[str] = set()
for obs in result.observations:
    if obs.task_id == "*":
        continue
    if obs.observation_type in _NON_BLOCKING_TYPES:
        continue
    if obs.observation_type == "reviewer_finding":
        if obs.detail.get("severity", "") in ("nit", "positive"):
            continue
    task_issues.add(obs.task_id)
```

**Problem 2: Fake detail fields.** `files_planned` and `files_actual` are both set to `len(files_touched)`, so they always match. `guardian` is hardcoded to `"aligned"`. `agent_model` is missing. `context_misses` and `context_waste_count` are hardcoded to 0.

Fixed detail:

```python
def _step9_success_observations(feature: str, tasks: dict[str, dict],
                                  task_issues: set[str],
                                  plan: dict | None,
                                  result: ExtractResult) -> None:
    plan_by_id: dict[str, list[str]] = {}
    if plan and isinstance(plan, dict):
        for pt in plan.get("tasks", []):
            if isinstance(pt, dict):
                plan_by_id[str(pt.get("id", ""))] = pt.get("files_touched", [])

    # Build guardian status per task from existing observations
    guardian_status: dict[str, str] = {}
    for obs in result.observations:
        if obs.observation_type == "guardian_verdict" and obs.task_id != "*":
            guardian_status[obs.task_id] = obs.detail.get("verdict", "unknown")

    for task_id, task in tasks.items():
        if task_id in task_issues:
            continue
        if task.get("status") != "done":
            continue

        duration = _duration_seconds(task)
        files_touched = task.get("files_touched", [])
        planned = plan_by_id.get(task_id, [])

        detail = {
            "files_planned": len(planned) if planned else len(files_touched),
            "files_actual": len(files_touched),
            "agent_model": task.get("agent_model", ""),
            "retry_count": 0,
            "guardian": guardian_status.get(task_id, "no_check"),
            "duration_seconds": duration,
        }
        result.observations.append(
            _make_obs(feature, "developer", task_id, "success", detail)
        )
```

Changes from current code:

| Field | Before | After |
|-------|--------|-------|
| `files_planned` | `len(files_touched)` (same as actual) | `len(planned)` from Architect plan, falls back to `len(files_touched)` |
| `files_actual` | `len(files_touched)` | `len(files_touched)` (unchanged) |
| `agent_model` | not present | `task.get("agent_model", "")` |
| `guardian` | `"aligned"` hardcoded | Derived from `guardian_verdict` observations, or `"no_check"` |
| `context_misses` | `0` hardcoded | Removed (context engine metric, not success metric) |
| `context_waste_count` | `0` hardcoded | Removed |
| `verify_clean` | `True` hardcoded | Removed (redundant with blocking logic) |
| `coherence_clean` | `True` hardcoded | Removed |
| `security_clean` | `True` hardcoded | Removed |
| `conditions` | `"Task scoped to N files"` | Removed (filler) |

**Expected impact across features:**

| Feature | Before | After | Newly eligible tasks |
|---------|--------|-------|---------------------|
| speed-defects | 0 | 5 | 4, 5, 9, 10b, 10c |
| speed-security | 0 | 1 | 11 |
| f9-profile-completeness | 0 | 4 | 2, 3, 5, 7 |
| f10-rich-feed | 0 | 0 | (all tasks have retries or gate failures) |
| seed-onboarding-flag | 0 | 0 | (task 1 has gate failures) |
| **Total** | **0** | **10** | |

**Known limitations:**

- **`files_planned` falls back to `files_actual` when no Architect plan exists.** speed-security has no Architect JSONL, so the one eligible task (11) will have `files_planned == files_actual`. This is documented, not hidden.
- **Guardian status is derived from observations, not raw files.** If Step 3 skipped a guardian file due to parsing errors, the status defaults to `"no_check"` rather than the true verdict. Acceptable since Step 3 bugs are Step 3's problem.
- **`retry_count` is hardcoded to 0.** A task in `task_issues` due to retries won't reach Step 9, so this is always accurate for success tasks. If a task retried and then succeeded, the retry observation already recorded the retry — the success observation just notes the final state.

**Test expectations:**

- Task with only nit reviewer findings → success observation emitted
- Task with only agent_concerns → success observation emitted
- Task with only context_miss → success observation emitted
- Task with retry → no success observation
- Task with gate_failure → no success observation
- Task with minor reviewer_finding → no success observation
- Task with status != "done" → no success observation
- `agent_model` populated from task JSON
- `guardian` derived from guardian_verdict observations, default `"no_check"`
- `files_planned` from Architect plan when available, falls back to `files_actual`
- All success observations use `stage="developer"` and per-task `task_id`, weight 0.5
- Real data: 5 successes in speed-defects, 1 in speed-security, 4 in f9-profile-completeness

---

### Step 10 — Pattern Detection

**Goal:** Identify observation types that recur across 3+ features, signaling systemic issues rather than one-off problems.

**Source data:**

| Input | Path | Format |
|---|---|---|
| Current feature observations | (in-memory from Steps 1-9) | `list[Observation]` |
| Prior feature observations | `.speed/memory/observations/*.jsonl` | One JSONL file per feature |

**Problem:** The grouping key includes `files_key` (a tuple of files from the observation's `files_involved` or `file` detail field). Each feature touches different files, so observations of the same type almost never share a `files_key`. Patterns that humans would spot ("retries keep happening across features") never fire.

Real data across 4 features (speed-security, f9-profile-completeness, f10-rich-feed, seed-onboarding-flag):
- Current code: **0 patterns** detected
- With fix: **2 patterns** detected (`retry` across 3 features, `reviewer_finding/unclassified` across 3 features)

**Solution:** Two-pass grouping. Pass 1 groups by `(type, files_key, category)` to catch file-specific recurring issues. Pass 2 groups by `(type, category)` only, excluding observations already matched in Pass 1, to catch type-level patterns where files differ across features.

```python
    # --- Pass 1: file-specific patterns ---
    groups_file: dict[tuple, list[Observation]] = {}
    for obs in all_obs:
        if obs.observation_type in ("pattern_match", "success"):
            continue
        files_key = _files_key(obs)
        category = _category(obs)
        key = (obs.observation_type, files_key, category)
        groups_file.setdefault(key, []).append(obs)

    covered_ids: set[str] = set()
    for key, obs_list in groups_file.items():
        features_in_group = {o.feature for o in obs_list}
        if len(features_in_group) >= min_features:
            obs_type, files_key, category = key
            _emit_pattern(obs_type, files_key, category, obs_list,
                         features_in_group, total_features, feature, patterns)
            covered_ids.update(o.id for o in obs_list)

    # --- Pass 2: type-level patterns (skip already-covered) ---
    groups_type: dict[tuple, list[Observation]] = {}
    for obs in all_obs:
        if obs.observation_type in ("pattern_match", "success"):
            continue
        if obs.id in covered_ids:
            continue
        category = _category(obs)
        key = (obs.observation_type, category)
        groups_type.setdefault(key, []).append(obs)

    for key, obs_list in groups_type.items():
        features_in_group = {o.feature for o in obs_list}
        if len(features_in_group) >= min_features:
            obs_type, category = key
            _emit_pattern(obs_type, (), category, obs_list,
                         features_in_group, total_features, feature, patterns)
```

**Severity and weight:**

| Features in group | Severity | Weight |
|---|---|---|
| 5+ | high | 3.0 |
| 3-4 | medium | 2.0 |
| < 3 | (not emitted) | — |

**Expected impact across real data (4 features):**

| Pattern | Features | Severity | Before fix |
|---|---|---|---|
| `retry` | 3/4 (speed-security, f9, f10) | medium | not detected |
| `reviewer_finding/unclassified` | 3/4 (speed-security, f9, f10) | medium | not detected |

**Known limitations:**

- **Requires 3+ features in `.speed/memory/observations/`.** A fresh project produces no patterns until 3 features have run `speed learn`. By design: fewer than 3 data points is noise.
- **`category` field is inconsistent across observation types.** Some use `category`, others use `finding_type` or `issue_type`. The code checks all three with a fallback chain. Observations with no category field group together by type alone, which can merge unrelated issues of the same type.

**Test expectations:**

- Below `min_features` threshold → empty list
- File-specific group crossing 3 features → pattern emitted with correct files in description
- Type-level group crossing 3 features (different files) → pattern emitted
- Observations covered by Pass 1 excluded from Pass 2 (no double-counting)
- `success` and `pattern_match` observations excluded from grouping
- Severity high at 5+ features, medium at 3-4
- Weight matches severity (3.0 / 2.0)
- Real data: 2 patterns from 4 features (retry, reviewer_finding/unclassified)

---

## API Surface

The system flow diagram above shows three layers: CLI command → bash bridge → Python pipeline. This section specifies each.

### `speed learn` CLI command

`speed learn` uses the global `--feature` / `-f` flag, consistent with all other SPEED subcommands (`speed run`, `speed review`, `speed integrate`, etc.). The feature is resolved from `GLOBAL_FEATURE`, which is parsed before subcommand dispatch.

```
speed [--feature <name>] learn [--summary] [--dry-run]
```

| Flag | Scope | Default | Description |
|------|-------|---------|-------------|
| `--feature`, `-f` | global | auto-detected | Feature to extract observations from. Resolves to `.speed/features/<name>/`. |
| `--summary` | learn | off | Print aggregate stats across all observed features instead of extracting. |
| `--dry-run` | learn | off | Run extraction, print what would be written, but don't write to disk. |

**Exit codes:**

| Code | Meaning |
|------|---------|
| 0 | Extraction completed (or nothing new to extract). |
| 1 | Extraction completed with warnings (missing artifacts, skipped tasks). |
| 2 | Fatal error (feature directory not found, no artifacts at all). |

### Integration with `speed integrate`

After successful integration, `speed integrate` prompts:

```
Integration complete. Run observation extraction? [Y/n]
```

Default is yes. On confirmation, `cmd_integrate()` calls `cmd_learn()` internally. A crash in `speed learn` logs an error but does not affect the integration exit code. The feature is integrated regardless.

### Bash bridge

The shell bridge (`lib/learn_bridge.sh`) follows the same pattern as `lib/context_bridge.sh`: bash functions that call into Python, sourced by the main orchestrator.

```bash
# lib/learn_bridge.sh
learn_extract() {
    local feature_dir="$1"
    local memory_dir="$2"

    # Pre-parse raw agent output files into clean JSON.
    # plan-verification.log and coherence.log contain markdown-wrapped
    # JSON (prose preamble + ```json fence + trailing summary).
    # parse_agent_json (lib/provider.sh) already handles this format
    # for every agent in the pipeline — no new parsing logic needed.
    local verify_json="" coherence_json=""
    if [[ -f "${feature_dir}/logs/plan-verification.log" ]]; then
        verify_json=$(parse_agent_json "$(cat "${feature_dir}/logs/plan-verification.log")") || verify_json=""
    fi
    if [[ -f "${feature_dir}/logs/coherence.log" ]]; then
        coherence_json=$(parse_agent_json "$(cat "${feature_dir}/logs/coherence.log")") || coherence_json=""
    fi

    # Write pre-parsed JSON to temp files for Python consumption.
    local tmp_verify tmp_coherence
    tmp_verify=$(mktemp "${TMPDIR:-/tmp}/_speed_verify_XXXXXX")
    tmp_coherence=$(mktemp "${TMPDIR:-/tmp}/_speed_coherence_XXXXXX")
    echo "$verify_json" > "$tmp_verify"
    echo "$coherence_json" > "$tmp_coherence"

    $(_learn_python) -c "
from lib.learn.extract import extract_observations, write_observations
from pathlib import Path
result = extract_observations(
    Path('$feature_dir'), Path('$memory_dir'),
    verify_json_path=Path('$tmp_verify'),
    coherence_json_path=Path('$tmp_coherence'),
)
wr = write_observations(result.observations, Path('$memory_dir') / 'observations' / '${GLOBAL_FEATURE}.jsonl')
print(result.summary())
print(wr.summary())
" 2>&1

    rm -f "$tmp_verify" "$tmp_coherence"
}
```

The bridge uses the same `_learn_python()` helper pattern as `_context_python()` in `context_bridge.sh`: checks `SPEED_PYTHON`, then `.venv/bin/python3`, then system `python3`.

Two raw agent output files (`plan-verification.log`, `coherence.log`) are pre-parsed in bash via `parse_agent_json` before passing to Python. All other artifact files (task JSON, review JSON, security-audit.json) are already clean JSON and are read directly by the Python pipeline.

### Python API

Extraction logic lives in `lib/learn/extract.py`. The CLI command (`cmd_learn()` in `lib/cmd/learn.sh`) is a thin shell wrapper that calls the bridge, which calls the Python module.

Three components. `extract.py` owns the pipeline, ID generation, observation I/O, and pattern detection. `classify.py` is a prototype-based text classifier (TF-IDF cosine similarity → optional embedding cascade → sklearn when trained → fallback) that reads category prototypes from a `.jsonl` data file. `lib/learn/data/review_categories.jsonl` defines the 67 prototype sentences across 7 categories. No other files in `lib/learn/` besides `__init__.py`.

```python
# ── lib/learn/extract.py ──────────────────────────────────────────────

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ObservationType = Literal[
    "retry", "reviewer_finding", "human_override", "guardian_verdict",
    "gate_failure", "context_miss", "context_waste", "decomposition_miss",
    "convention_violation", "verify_finding", "coherence_issue",
    "security_finding", "success", "pattern_match", "unattributed_changes",
    "agent_concern",
]

Stage = Literal[
    "developer", "reviewer", "guardian", "verifier", "coherence",
    "security", "context", "architect", "meta", "human",
]


@dataclass
class Observation:
    """Single observation from the extraction pipeline."""

    id: str                        # "sha256:<hex>" — from observation_id()
    feature: str                   # feature name from .speed/features/<name>/
    stage: Stage                   # pipeline stage that produced the artifact
    task_id: str                   # task identifier, or "*" for feature-level
    timestamp: str                 # ISO 8601 — extraction time, not event time
    observation_type: ObservationType
    detail: dict                   # type-specific fields (see Data Model)
    weight: float                  # base weight for synthesis prioritization


@dataclass
class ExtractResult:
    """Output of the 10-step extraction pipeline."""

    observations: list[Observation]
    warnings: list[str]            # skipped steps, missing files
    errors: list[str]              # malformed artifacts, parse failures

    def by_type(self) -> dict[str, list[Observation]]:
        """Groups observations by observation_type."""
        groups: dict[str, list[Observation]] = {}
        for obs in self.observations:
            groups.setdefault(obs.observation_type, []).append(obs)
        return groups

    def summary(self) -> str:
        """One-line summary for CLI output.

        Example: "16 observations (4 success, 3 reviewer_finding, 1 retry, ...)"
        """
        counts = {t: len(obs) for t, obs in self.by_type().items()}
        parts = [f"{n} {t}" for t, n in sorted(counts.items(), key=lambda x: -x[1])]
        total = len(self.observations)
        return f"{total} observations ({', '.join(parts)})"


@dataclass
class WriteResult:
    """Output of write_observations()."""

    written: int                   # new observations appended
    skipped: int                   # duplicate IDs already in file
    warnings: list[str]            # corrupt lines encountered during read

    def summary(self) -> str:
        return f"{self.written} written, {self.skipped} skipped"


def extract_observations(feature_dir: Path, memory_dir: Path,
                         verify_json_path: Path | None = None,
                         coherence_json_path: Path | None = None) -> ExtractResult:
    """Reads pipeline artifacts and runs the 10-step extraction pipeline.

    Args:
        feature_dir: Path to .speed/features/<name>/. Contains per-task
            artifacts in tasks/, logs/ subdirectories and feature-level
            files (security-audit.json).
        memory_dir: Path to .speed/memory/. Used by Step 10 to read
            prior feature observations for pattern detection.
        verify_json_path: Path to pre-parsed plan verification JSON.
            The bridge pre-parses plan-verification.log (markdown-wrapped
            agent output) via parse_agent_json in bash, writes clean JSON
            to a temp file, and passes the path here. None if the file
            didn't exist or parsing failed.
        coherence_json_path: Path to pre-parsed coherence JSON. Same
            pre-parsing approach as verify_json_path.

    Returns:
        ExtractResult with observations, warnings, and errors.

    Steps 1-3 iterate per-task artifacts. Step 1 produces retry,
    gate_failure, unattributed_changes, and agent_concern observations.
    Retry detection uses both retry_count (explicit) and
    review_verdict=request_changes (implicit). Retry detail includes
    timeout_count and agent_model per product spec. Agent concerns
    are extracted from the task JSON concerns[] array with a
    predictive flag when the task was later rejected. Clean tasks
    produce nothing here — they're handled by Step 9. Step 3 reads
    guardian JSON files (`logs/guardian-*.json`) as the primary source,
    extracting verdicts, scope violations, flags, and persona grounding
    failures. Falls back to task JSON `review_feedback` for rejections
    when guardian files have been pruned (features with 8+ tasks). Steps 4-6
    read single feature-level files. Steps 7-8 cross-reference
    code-context JSON against git diff. Step 9 produces success
    observations for tasks that passed all gates clean (no overlap
    with Step 1). Step 10 calls detect_patterns() against prior
    features, then train_classifier() if enough data has accumulated.

    Never raises. Missing artifacts skip the step (warning). Malformed
    JSON skips the task (error).
    """


def observation_id(feature: str, task_id: str, stage: str,
                   obs_type: str, detail: dict) -> str:
    """Produces a deterministic content-hash ID for an observation.

    Args:
        feature:  Feature name (e.g. "speed-security").
        task_id:  Task identifier (e.g. "3") or "*" for feature-level.
        stage:    Pipeline stage (e.g. "developer").
        obs_type: Observation type (e.g. "retry").
        detail:   Type-specific detail dict.

    Returns:
        String in format "sha256:<64 hex chars>".

    Computation:
        1. Canonical JSON: json.dumps(detail, sort_keys=True, separators=(',', ':'))
        2. Concatenate: f"{feature}\\n{task_id}\\n{stage}\\n{obs_type}\\n{canonical}"
        3. SHA-256 hash the UTF-8 encoded string.
        4. Return f"sha256:{hex_digest}"

    Example:
        >>> observation_id("speed-security", "3", "developer", "retry",
        ...   {"what_happened": "Missing template", "files_involved": ["lib/toml.py"]})
        'sha256:a7c3f2e9...'

        Canonical detail: {"files_involved":["lib/toml.py"],"what_happened":"Missing template"}
        sort_keys enforces key ordering, so dict key order in the caller
        doesn't affect the ID.

    This is what makes extraction idempotent. write_observations() loads
    existing IDs before appending, so re-extracting produces no duplicates.
    """


def write_observations(observations: list[Observation],
                       output_path: Path) -> WriteResult:
    """Appends observations to a JSONL file, skipping duplicates.

    Args:
        observations: Observations to write (from ExtractResult).
        output_path:  Path to the feature's .jsonl file.

    Returns:
        WriteResult with write/skip counts and corruption warnings.

    Procedure:
        1. Create output_path and parent dirs if missing.
        2. Read existing lines, parse as JSON, collect IDs into a set.
           Unparseable lines are skipped (warning).
        3. Skip observations whose ID already exists. Serialize new
           ones as compact JSON.
        4. Write each line + newline via single os.write() call. Atomic
           on local filesystems at this size (<4KB, under PIPE_BUF).
        5. fsync after all writes complete.
    """


def detect_patterns(current: list[Observation], prior_dir: Path,
                    min_features: int = 3) -> list[Observation]:
    """Finds recurring patterns across feature runs.

    Args:
        current:      Observations from the current feature extraction.
        prior_dir:    Path to .speed/memory/observations/ (*.jsonl files).
        min_features: Minimum distinct features for a group to qualify
                      as a pattern. Default: 3.

    Returns:
        List of pattern_match Observations (not yet written). The caller
        passes them through write_observations() with everything else.

    Grouping key: (observation_type, frozenset(detail.files_involved),
    detail.category or detail.finding_type). Observations without
    files_involved use (observation_type, detail.category) only.

    Each pattern_match detail contains:
        pattern:     Human-readable description of the recurring issue.
        occurrences: List of {feature, task_id, observation_id} dicts.
        frequency:   "N of last M features" string.
        severity:    "high" (5+), "medium" (3-4), "low" (at threshold).
    """


# ── lib/learn/classify.py ────────────────────────────────────────────

from dataclasses import dataclass
from pathlib import Path

#
# Prototype-based text classifier. Classifies free text by cosine
# similarity against TF-IDF-vectorized prototype sentences.
#
# Stage progression: prototype (TF-IDF + optional embedding cascade)
# → sklearn (if trained) → fallback
#
# Prototypes are loaded from lib/learn/data/review_categories.jsonl.
# Categories are defined by the prototype file, not by code.
#
# Current consumers:
#   - Step 2 (review findings): 7 categories, see REVIEW_PROTOTYPES


@dataclass
class ClassifyResult:
    """Output of classify()."""

    category: str              # winning category name, or "unclassified"
    stage: str                 # "prototype" | "prototype_embed" | "sklearn" | "fallback"
    confidence: float          # prototype: cosine similarity. sklearn: predict_proba. fallback: 0.0
    scores: dict[str, float]   # per-category max similarity


def _load_prototypes(path: Path) -> dict[str, list[str]]:
    """Load prototypes from .jsonl file. Raises if missing or empty."""


def classify(text: str,
             prototypes: dict[str, list[str]],
             model_path: Path | None = None,
             min_similarity: float = 0.08,
             cascade_threshold: float = 0.20) -> ClassifyResult:
    """Classifies free text into one of the prototype categories.

    Args:
        text:               Text to classify.
        prototypes:         Dict mapping category name to list of prototype
                            sentences. Categories are the dict keys.
        model_path:         Path to a trained sklearn model (.pkl). If the file
                            exists, Stage 2 uses it. If None or missing, Stage 2
                            is skipped. See train_classifier().
        min_similarity:     Minimum cosine similarity to accept a prototype match.
        cascade_threshold:  If TF-IDF similarity is between min_similarity and
                            this threshold, cascade to embedding similarity
                            (if fastembed is available).

    Returns:
        ClassifyResult with winning category, resolution stage,
        confidence, and per-category similarity scores.

    Stage 1 (prototype):
        TF-IDF-vectorize the text and compute cosine similarity against
        all prototype sentences. If the best match scores >= cascade_threshold,
        return that category. If between min_similarity and cascade_threshold,
        cascade to sentence embeddings (fastembed) if available.
        The vectorizer and prototype matrix are computed once per process.

    Stage 2 (sklearn):
        If Stage 1 is inconclusive and model_path points to a trained
        model, load it (cached after first load) and predict. The model
        is a TfidfVectorizer + SGDClassifier pipeline saved via joblib.
        Accepts the prediction if predict_proba >= 0.7.

    Stage 3 (fallback):
        If no prior stage resolved, return category="unclassified".
    """


def train_classifier(observations_dir: Path,
                     model_path: Path,
                     min_samples: int = 200) -> bool:
    """Trains an sklearn classifier from accumulated labeled observations.

    Args:
        observations_dir: Path to .speed/memory/observations/ (*.jsonl).
        model_path:       Where to save the trained model (.pkl).
        min_samples:      Minimum labeled reviewer_finding observations
                          required before training. Default: 200.

    Returns:
        True if a model was trained and saved, False if insufficient data.

    Called internally by extract_observations() after Step 10. Scans all
    JSONL files for reviewer_finding observations with a non-"unclassified"
    category. If the count meets min_samples:

        1. Collect (text, category) pairs from reviewer_finding details.
        2. Build a sklearn Pipeline: TfidfVectorizer + SGDClassifier.
        3. Train with 80/20 stratified split. Log accuracy on held-out set.
        4. Save via joblib.dump() to model_path.

    Retrains on every invocation once the threshold is met, incorporating
    new observations. The model file is small (~50-200KB). Training takes
    <1s on 200-1000 observations. Subsequent classify() calls pick up the
    new model automatically.

    The trained model lives at .speed/memory/models/review_classifier.pkl.
    It is gitignored alongside the observations directory.
    """


# ── Prototypes ───────────────────────────────────────────────────────

REVIEW_PROTOTYPES: dict[str, list[str]] = _load_prototypes(
    Path(__file__).parent / "data" / "review_categories.jsonl"
)
```

## Data Model

The extraction pipeline produces observations. This section defines their structure.

### Directory layout

```
.speed/memory/
  observations/                    # Append-only observation logs
    speed-security.jsonl           # One file per feature
    speed-auth.jsonl
    ...
  models/                          # Auto-trained classifiers
    review_classifier.pkl          # Created once 200+ labeled observations exist
  extraction-meta.json             # Extraction state (last run per feature, checksums)
```

The `observations/` directory is created on first `speed learn` invocation. Files inside are append-only: the system writes lines, never modifies or deletes them. The human can delete files manually if needed.

### Observation schema

Every observation follows a single envelope schema. The `detail` object varies by `observation_type`.

```json
{
  "id": "string",
  "feature": "string",
  "stage": "developer | reviewer | guardian | verifier | coherence | security | context | architect | meta | human",
  "task_id": "string | '*'",
  "timestamp": "ISO 8601",
  "observation_type": "string (enum)",
  "detail": {},
  "weight": 0.0
}
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Deterministic hash. Format: `sha256:<hex>`. Derived from `(feature, task_id, stage, observation_type, canonical_detail)`. See `observation_id()` in the API section. |
| `feature` | string | Feature name from `.speed/features/<name>/`. |
| `stage` | string | Which pipeline stage produced the source artifact. |
| `task_id` | string | Task identifier, or `"*"` for feature-level observations (verify, coherence, security). |
| `timestamp` | string | ISO 8601 timestamp of extraction, not of the original event. |
| `observation_type` | string | One of the 16 types defined below. |
| `detail` | object | Type-specific structured data. Varies per `observation_type`. |
| `weight` | float | Base weight for synthesis prioritization. Set at extraction time. |

### Observation types and detail schemas

**`retry`** (weight: 3.0) — A task required one or more retries. Detected from `retry_count > 0` (explicit) or `review_verdict == "request_changes"` (implicit, for tasks where `task_request_changes()` didn't increment `retry_count`).

```json
{
  "retry_count": 2,
  "timeout_count": 1,
  "agent_model": "opus",
  "what_happened": "Reviewer requested changes (resolved)",
  "evidence": "retry_count=2, timeout_count=1",
  "resolution": "status=done",
  "files_involved": ["lib/toml.py", "templates/speed-toml.toml"],
  "duration_seconds": 284
}
```

`timeout_count` tracks how many times the agent hit the time limit (distinct from review rejections). `agent_model` records which model was assigned to the task (e.g., `"sonnet"` or `"opus"`), supporting model escalation analysis. `what_happened` is derived from task state: `error` field if set, `"Reviewer requested changes"` if `review_verdict == "request_changes"`, `"Reviewer requested changes (resolved)"` if verdict was overwritten to `approve` after a retry, or `"Retried"` as fallback. `evidence` lists the fields that triggered detection.

**`reviewer_finding`** (weight: 1.5 confirmed, 0.5 dismissed) — The Reviewer flagged an issue, or a structured reviewer output (spec verification, missing from spec, out of scope, strength) was extracted.

```json
{
  "category": "convention | correctness | scope | testing | maintainability | performance | spec_alignment | strength",
  "finding": "Template not updated alongside parser change",
  "severity": "major | minor | nit | positive",
  "suggestion": "Update template alongside parser change",
  "confirmed": true,
  "led_to_retry": true,
  "file": "lib/toml.py",
  "line": 42,
  "evidence": "(optional, spec_verification only) code evidence from reviewer",
  "spec_section": "(optional, spec_verification only) spec section reference"
}
```

Source arrays: `issues[]` (classified by prototype matching), `spec_verification[]` (non-satisfied items, category `spec_alignment`), `missing_from_spec[]` (category `spec_alignment`), `out_of_scope[]` (category `scope`), `strengths[]` (category `strength`, weight 0.5).

`confirmed` is true when `retry_count > 0` or `review_verdict == "request_changes"` for `issues[]` and `spec_verification[]`. For `missing_from_spec[]`, `out_of_scope[]`, and `strengths[]`, `confirmed` is always true — these are the reviewer's explicit structured judgments, not ambiguous findings. `led_to_retry` is true only when `retry_count > 0`. These are independent fields.

**`human_override`** (weight: 2.5) — A task was guardian-rejected but eventually completed. Detected when task JSON has `review_feedback` starting with `"GUARDIAN REJECTED"` and `status == "done"`. The operator either fixed the issue and re-ran (developer addressed the vision concern) or bypassed with `SKIP_GUARDIAN=true` (indistinguishable from task JSON). Both cases carry learning signal: the guardian flagged something the operator decided to proceed past.

Note: `task_request_changes()` sets `status = "pending"` without incrementing `retry_count`. The task re-enters the normal `speed run` pipeline. If the reviewer later rejects and overwrites `review_feedback` with review JSON, the guardian rejection is lost and no `human_override` observation is produced.

```json
{
  "original_rejection": "GUARDIAN REJECTED: Vision violation detected in security header implementation",
  "task_status": "done",
  "review_verdict": "approve",
  "retry_count": 0
}
```

`retry_count` may be 0 even after a guardian rejection because `task_request_changes()` does not increment it (only `task_reset_pending()` does, which is the `speed retry` path for failed/blocked tasks).

**`guardian_verdict`** (weight: varies by subtype) — Product Guardian evaluation of a task or feature against the project's vision document. See [Step 3: Guardian Verdicts](#step-3-guardian-verdicts) for the full extraction logic, source data, and known limitations.

Primary source: guardian JSON files (`logs/guardian-*.json`). Fallback: task JSON `review_feedback` starting with `"GUARDIAN REJECTED"`. All observations carry a `subtype` key for downstream filtering.

```json
{
  "subtype": "verdict | scope_violation | flag | persona_not_served",
  "verdict": "flagged",
  "summary": "TRIBE_ANNOUNCEMENT is structurally identical to a text post",
  "behavioral_test": "misaligned",
  "behavioral_reasoning": "Feature introduces excluded capability",
  "scope_violation_count": 1,
  "flag_count": 2,
  "differentiation_direction": "weakens",
  "check_type": "post-review",
  "source_file": "guardian-post-review-1772439353.json"
}
```

Subtype-specific schemas:

| Subtype | Weight | Key fields |
|---------|--------|------------|
| `verdict` | 1.0 | `verdict`, `summary`, `behavioral_test`, `behavioral_reasoning`, `check_type`, `source_file` |
| `scope_violation` | 2.0 | `feature_name`, `maps_to`, `severity`, `reasoning`, `source_file` |
| `flag` | 1.5 | `severity`, `description`, `vision_reference`, `recommendation`, `source_file` |
| `persona_not_served` | 1.0 | `persona`, `use_case`, `source_file` |

Task JSON fallback produces a simpler detail:

```json
{
  "subtype": "verdict",
  "verdict": "rejected",
  "summary": "Vision violation: feature introduces excluded capability",
  "task_final_status": "done | pending",
  "led_to_rerun": true,
  "source_file": "task_json"
}
```

**`gate_failure`** (weight: 2.0) — A quality gate rejected the task output. Produced by Step 1 by scanning gate log files for all tasks and correlating by timestamp window. Gate logs are scanned regardless of the task JSON `error` field because upstream does not reliably set it.

```json
{
  "gate": "lint | typecheck | test | grounding",
  "error_summary": "TypeCheck failed: missing return type annotation",
  "file": "lib/security.py",
  "line": 23
}
```

**`context_miss`** (weight: 1.5) — A file was modified but not included in the context package.

```json
{
  "file": "lib/context_bridge.sh",
  "reason": "Modified by developer but not in context package",
  "hop_distance": 2,
  "task_files_declared": ["lib/security.py", "lib/auth.py"]
}
```

**`context_waste`** (weight: 0.5) — A file was included in context but never referenced.

```json
{
  "file": "lib/context/utils.py",
  "reason": "Included as 1-hop neighbor but never referenced in diff or reasoning",
  "tier": "full | skeleton",
  "tokens_consumed": 450
}
```

**`decomposition_miss`** (weight: 2.0) — Planned file boundaries didn't match actual execution.

```json
{
  "issue": "boundary_mismatch | missing_dependency | scope_too_broad",
  "planned_files": ["lib/toml.py", "lib/security.py", "tests/test_security.py"],
  "actual_files": ["lib/toml.py", "lib/security.py", "tests/test_security.py", "templates/speed-toml.toml", "lib/__init__.py"],
  "analysis": "Task touched 5 files instead of 3. Template and init updates were cascading dependencies not captured in plan."
}
```

**`convention_violation`** (weight: 1.5) — Code violated a known project convention. Not produced by the extraction pipeline on day one. Reserved for future use by convention discovery (speed-conventions), which will match review findings against a convention registry and produce these observations. Until then, convention-related findings appear as `reviewer_finding` with `category: "convention"`.

```json
{
  "convention_id": "conv-http-wrapper",
  "convention": "HTTP calls go through lib/api/client.py:fetch()",
  "violation": "Direct httpx.get() call in lib/security.py:67",
  "source": "reviewer | guardian | human"
}
```

**`verify_finding`** (weight: 2.0) — The plan verifier detected spec drift or a critical failure.

```json
{
  "finding_type": "spec_drift | critical_failure | missing_requirement",
  "requirement": "Security header format",
  "status": "drifted | missing",
  "spec_location": "Section 3.2",
  "analysis": "Header format in spec uses X-Security-Token but codebase already migrated to Authorization: Bearer"
}
```

**`coherence_issue`** (weight: 2.0) — The coherence checker found a cross-task conflict.

```json
{
  "issue_type": "interface_mismatch | schema_inconsistency | missing_connection",
  "task_a": "2",
  "task_b": "4",
  "location_a": "lib/security.py:45",
  "location_b": "lib/auth.py:112",
  "description": "validate_token() returns bool in task 2 but task 4 expects Optional[TokenInfo]",
  "severity": "critical | warning"
}
```

**`security_finding`** (weight: 1.5) — The security auditor identified a vulnerability.

```json
{
  "finding_id": "SEC-001",
  "severity": "critical | high | medium | low | info",
  "category": "injection | auth | secrets | crypto | config | xss | path-traversal | info-disclosure",
  "title": "Hardcoded timeout value",
  "file": "lib/security.py",
  "line": 23,
  "recommendation": "Move to configuration"
}
```

**`success`** (weight: 0.5) — A task passed all gates on first attempt with no issues.

```json
{
  "files_planned": 3,
  "files_actual": 3,
  "retry_count": 0,
  "context_misses": 0,
  "context_waste_count": 0,
  "guardian": "cleared",
  "verify_clean": true,
  "coherence_clean": true,
  "security_clean": true,
  "duration_seconds": 142,
  "conditions": "Task scoped to 3 files in lib/toml.py area, test files included as full content"
}
```

**`pattern_match`** (weight: varies) — A recurring observation detected across features.

```json
{
  "pattern": "retry on tasks touching lib/toml.py due to missing template update",
  "occurrences": [
    {"feature": "speed-auth", "task_id": "2", "observation_id": "sha256:b2d4..."},
    {"feature": "speed-config", "task_id": "4", "observation_id": "sha256:e8f1..."},
    {"feature": "speed-security", "task_id": "3", "observation_id": "sha256:a7c3..."}
  ],
  "frequency": "3 of last 4 features",
  "severity": "high | medium | low"
}
```

**`unattributed_changes`** (weight: 1.0) — Manual commits on the feature branch that don't correspond to any task. Produced by Step 1 by comparing feature branch commit SHAs against the set of commit SHAs recorded in all task JSONs. PRD priority: Should.

```json
{
  "commits": ["a1b2c3d", "e4f5g6h"],
  "files": ["lib/config.py", "tests/test_config.py"],
  "reason": "2 commits on feature branch not attributed to any task"
}
```

**`agent_concern`** (weight: 1.0) — The developer agent flagged a risk or concern during task execution. Extracted from the `concerns[]` array in task JSON. Concerns are predictive: the agent identified something that might cause problems. When `predictive` is true, the task was later rejected by the reviewer, meaning the agent anticipated its own failure.

```json
{
  "concern": "Existing test now fails because it looks for old EVENT_LABELS text that no longer exists. Task 4 will rewrite all tests.",
  "agent_model": "opus",
  "task_status": "pending",
  "review_verdict": "request_changes",
  "predictive": true
}
```

`decisions[]` (also in task JSON) are not extracted. Decisions are implementation choices ("Used Unicode middle dot for separator") that are informational, not predictive. Concerns flag risk; decisions describe approach.

### Extraction metadata schema

Tracks what has been extracted to support idempotency and incremental runs.

```json
{
  "features": {
    "speed-security": {
      "last_extracted": "2026-03-06T14:22:00Z",
      "observation_count": 16,
      "artifact_checksums": {
        "1.json": "sha256:...",
        "review-1.json": "sha256:...",
        "guardian-post_review-*.json": "sha256:..."
      }
    }
  }
}
```

## Review Finding Classification

Classification is the one step in the extraction pipeline that requires interpretation. Every other step reads structured JSON fields directly. Review findings are free-form text from the Reviewer agent, and they need to be categorized before downstream synthesis can group them by type.

### The problem

The Reviewer produces findings like:

```json
{
  "severity": "major",
  "file": "lib/security.py",
  "line": 42,
  "message": "Dict value accessed with .get() without checking type first. If the TOML section contains a string instead of a table, this will raise AttributeError.",
  "suggestion": "Add isinstance(section, dict) guard before accessing keys."
}
```

Synthesis needs to know: is this a `correctness` issue (bug), a `convention` issue (project pattern), or a `testing` issue (missing coverage)? The answer determines which learnings file receives the pattern and which agent gets the guidance.

### Category definitions

Six categories. Each has a distinct downstream consumer and a clear boundary separating it from its neighbors.

| Category | Definition | Downstream consumer | Boundary note |
|----------|-----------|-------------------|--------------|
| `convention` | Code violates a project-specific pattern: naming, structure, wrapper usage, import style. The code works, but it doesn't match how this project does things. | `conventions.json`, `developer-learnings.json` | Distinguished from `maintainability` by specificity. "Use `lib/api/client.py:fetch()` instead of raw httpx" is a convention. "This variable name is unclear" is maintainability. |
| `correctness` | Bug, logic error, crash risk, or wrong return value. The code doesn't do what the spec says, or it fails on valid input. | `developer-learnings.json` (retry self-knowledge) | Distinguished from `testing` by what's wrong. A missing null check is correctness. A missing *test* for the null case is testing. Distinguished from `spec_alignment` by whether the code is functionally broken. "Function returns wrong value" is correctness. "Log message says X but spec says Y" is spec_alignment. |
| `scope` | Work outside the task's declared boundaries. Files modified that weren't in `files_touched`, features added beyond the spec, unnecessary helpers or utilities. Also used for `out_of_scope[]` items from reviewer output. | `guardian-learnings.json` | Only applies when the change itself is out of bounds, not when it's wrong within bounds. An incorrect implementation of an in-scope feature is correctness, not scope. |
| `testing` | Missing, incomplete, or inadequate tests. The implementation may be correct, but the test coverage doesn't verify it. Includes missing edge cases, missing parametrization, and absent test files. | `developer-learnings.json` (testing patterns) | Distinguished from `correctness` by what needs to change. If the fix is "add a test," it's testing. If the fix is "change the implementation," it's correctness. |
| `maintainability` | Formatting, readability, dead code, naming clarity. Not a bug, not a project convention. Generic code quality that any reviewer on any project might flag. | Low-weight signal. Informs conventions only if a consistent pattern emerges across features. | Distinguished from `convention` by generality. "Unused import" is maintainability (universal). "Use relative imports in `lib/context/`" is convention (project-specific). Distinguished from `spec_alignment` by whether a spec prescribes the alternative. |
| `performance` | Efficiency concern, algorithmic complexity, unnecessary allocations, missing caching. The code works but is slower than it should be. | `developer-learnings.json` | Rare in practice. Most SPEED-generated code operates on small datasets. Included for completeness and for projects where performance is a core concern. |
| `spec_alignment` | Implementation diverges from what the product spec, tech spec, or design document defines. Code works, isn't a bug, but doesn't match the spec's prescribed wording, template, structure, or requirement coverage. | Spec drift detection, convention candidates | Distinguished from `correctness` by whether the code is functionally broken. Distinguished from `maintainability` by whether a spec prescribes the alternative. Also produced from `spec_verification[]` (non-satisfied items) and `missing_from_spec[]` arrays. |
| `strength` | Positive observation from reviewer `strengths[]` array. The reviewer noted something done well. | Convention candidates (recurring strengths become conventions) | Not a problem finding. Weight 0.5. Severity "positive". |

These categories are the contract between extraction (Phase 1) and synthesis (Phase 3). Synthesis groups observations by category to produce agent-specific guidance. Changing the category set requires updating the prototype file (`lib/learn/data/review_categories.jsonl`) and the synthesis pipeline.

### Prototype classifier

`classify.py` classifies free text by cosine similarity against prototype sentences. Review finding classification calls it as:

```python
from lib.learn.classify import classify, REVIEW_PROTOTYPES
from pathlib import Path

result = classify(
    text=f"{finding['message']} {finding['suggestion']}",
    prototypes=REVIEW_PROTOTYPES,
    model_path=Path(".speed/memory/models/review_classifier.pkl"),
)
# result.category = "correctness"
# result.stage = "prototype"
# result.scores = {"correctness": 0.44, "testing": 0.12, "convention": 0.08, ...}
```

The stages apply in order:

```
Input text + prototypes dict
        ↓
  Stage 1: TF-IDF cosine similarity against prototypes
        ↓
  similarity >= cascade_threshold (0.20)? ──yes──→ Return category
        │
  similarity >= min_similarity (0.08)?
        │
       yes → Cascade to embedding similarity (if fastembed available)
        │         └──→ Return embedding result
        │    or accept TF-IDF result (if fastembed unavailable)
        │
       no (below min_similarity)
        ↓
  Stage 2: sklearn (if model_path exists)
        ↓
  predict_proba >= 0.7? ──yes──→ Return category
        │
       no (or no model)
        ↓
  Stage 3: Fallback → "unclassified"
```

### Stage 1: Prototype matching

Prototypes are short sentences that describe behaviors typical of each category, loaded from `lib/learn/data/review_categories.jsonl`. Each line is `{"category": "correctness", "text": "injection via variable interpolation in shell string"}`. 67 prototypes across 7 categories.

Classification works by TF-IDF bigram vectorization and cosine similarity. The finding "Shell injection via heredoc variable interpolation" shares the bigrams "injection via" and "variable interpolation" with the correctness prototype "injection via variable interpolation in shell string." TF-IDF captures this overlap; cosine similarity ranks it highest among all prototypes.

The vectorizer and prototype matrix are computed once per process (~2ms) and cached. Subsequent classifications are a single sparse matrix multiply (<0.1ms). Deterministic: same finding always gets the same classification.

When TF-IDF similarity falls between `min_similarity` (0.08) and `cascade_threshold` (0.20), the classifier cascades to sentence embeddings via fastembed (`BAAI/bge-small-en-v1.5`) if available. Embeddings capture semantic meaning where TF-IDF needs word overlap. The cascade adds ~500ms on first call (model load) and handles edge cases where domain-specific vocabulary has zero TF-IDF overlap with prototypes.

A misclassification is fixed by adding one sentence to the prototype file. No code changes, no retraining, no API calls.

### Stage 2: sklearn classification

Findings below `min_similarity` check for a trained sklearn model at `.speed/memory/models/review_classifier.pkl`. If the model file exists, `classify()` loads it (cached after first load per process) and calls `predict_proba()`. If the highest probability exceeds 0.7, that category wins.

The model is a `sklearn.pipeline.Pipeline` containing `TfidfVectorizer` + `SGDClassifier(loss='modified_huber')`. Training happens automatically via `train_classifier()` at the end of each `speed learn` run once 200+ labeled observations exist.

On day one, no model file exists and Stage 2 is skipped. Prototype matching (Stage 1) handles ~90-100% of findings from the start, generating labeled observations that accumulate toward the 200-sample threshold.

### Fallback

If no prior stage resolves, the finding is classified as `"unclassified"` with confidence 0.0.

```
Prototype match (TF-IDF + cascade) → category     ← ~90-100% of findings, <1ms
sklearn (if model exists)          → category     ← activates after 200+ observations, <5ms
all stages fail                    → unclassified ← retried next run
```

### Review JSON segmentation

The Reviewer's output format (from the artifact exploration) already segments findings as individual objects in an `issues[]` array, each with `severity`, `file`, `line`, `message`, and `suggestion` fields. Classification operates on each issue independently. No segmentation step is needed.

If a review JSON contains only a top-level `verdict` with no `issues[]` array (approved without findings), no `reviewer_finding` observations are produced for that task.

### Evolution path

| Phase | Mechanism | LLM calls per feature | Trigger |
|-------|-----------|----------------------|---------|
| Phase 1 (day one) | Prototype matching (TF-IDF + optional embedding cascade) | 0 | Always active |
| Phase 2 (automatic) | sklearn classifier handles findings below prototype threshold | 0 | 200+ labeled observations accumulated |
| Phase 3 (future) | Reviewer tags findings at generation time; post-hoc classification validates tags | 0 | Reviewer prompt change (separate feature) |

Phase 1 is fully functional from the first feature. Prototype matching produces labeled observations that accumulate toward the Phase 2 threshold.

Phase 2 activates automatically. After each `speed learn` run, `train_classifier()` checks the observation count. Once 200+ `reviewer_finding` observations with non-"unclassified" categories exist (approximately 10-15 features), it trains a `TfidfVectorizer` + `SGDClassifier` pipeline and saves the model. sklearn is already installed in `.venv/` for the related spec compression feature.

Phase 3 modifies the Reviewer prompt to include a `category` field in each issue. When present, extraction reads the tag directly and skips classification entirely.

## Validation Rules

| Field | Constraint |
|-------|-----------|
| `id` | Must match `sha256:[a-f0-9]{64}`. Deterministic: same inputs produce same ID. |
| `feature` | Non-empty string. Must correspond to a directory in `.speed/features/`. |
| `stage` | One of: `developer`, `reviewer`, `guardian`, `verifier`, `coherence`, `security`, `context`, `architect`, `meta`, `human`. |
| `task_id` | Numeric string (`"1"`, `"2"`) or `"*"` for feature-level observations. |
| `observation_type` | One of the 16 types defined in the data model. |
| `detail` | Must be a non-empty JSON object conforming to the schema for its `observation_type`. |
| `weight` | Positive float. Set from the base weight table, not user-configurable. |
| `timestamp` | Valid ISO 8601 string. |

Validation runs before writing each observation. Invalid observations are logged to stderr and skipped. A single malformed observation never prevents other valid observations from being written.

## Security & Controls

**No new PII surfaces.** Observations contain file paths, line numbers, retry counts, finding categories, and timing data. No user data, credentials, or personal information. Code snippets are not stored in observations. The security finding observations reference file and line but store only the finding title and recommendation from the security audit output, not the code snippet itself.

**Append-only storage.** JSONL files are never modified or deleted by the system. Each line is an independent, valid JSON object. Corruption of one line (e.g., partial write during power loss) does not affect any other line. The extraction pipeline reads existing IDs by parsing each line independently and skipping unparseable lines with a warning.

**No LLM calls for classification.** Review finding classification uses TF-IDF prototype matching and optional sentence embeddings (fastembed, local model). No API calls for classification at any stage.

**Local-only.** All data stays in `.speed/memory/`. No network calls. The observation directory is gitignored by default (added to `.gitignore` on first creation).

**No escalation of privilege.** `speed learn` reads pipeline artifacts that the operator already produced. It writes to `.speed/memory/`, which the operator owns. No new file permissions, no new processes, no new network access beyond the existing `claude_run()` infrastructure.

## Key Decisions

| Decision | Choice | Alternatives Considered | Rationale |
|----------|--------|------------------------|-----------|
| Observation ID scheme | SHA-256 of canonical content fields | UUID5 (namespace-based), sequential counters, random UUIDs | SHA-256 is deterministic from content alone, no namespace coordination needed. UUID5 requires a namespace UUID and produces shorter IDs but adds a dependency. Sequential counters break across re-runs. Content-addressed IDs give idempotency for free. |
| Storage format | JSONL (one file per feature) | SQLite, single large JSONL, directory of individual JSON files | JSONL is append-only by nature, human-readable, greppable, and survives partial writes. SQLite adds a dependency and makes append-only semantics harder to guarantee. One-file-per-feature keeps files small and feature-scoped. Individual JSON files create filesystem pressure at scale. |
| Review finding classifier | TF-IDF prototype matching → optional embedding cascade → sklearn (auto-activates) → fallback | Pure LLM (accurate but slow/expensive/external dependency), pure sklearn (fast but needs training data), keyword matching (fast but vocabulary mismatch with reviewer language — validated at 12% accuracy on real findings) | 67 prototype sentences vectorized with TF-IDF bigrams; classification is cosine similarity (<1ms). Validated at 90% on 41 held-out findings from speed-security, 68% cross-domain on find-your-tribe. Zero API calls, zero new dependencies. Embedding cascade (fastembed, optional) adds 3pp for low-confidence matches. sklearn activates after 200+ labeled observations, trained on prototype-generated labels. |
| Pattern matching algorithm | Exact match on structured key fields | TF-IDF similarity, embedding-based clustering, manual tagging | At the expected scale (tens to low hundreds of observations), exact-match grouping by `(observation_type, files_involved_hash, detail.category)` is sufficient and deterministic. Similarity-based approaches are overkill and introduce false-positive patterns. The structured observation schema already normalizes the comparison fields. |
| Context effectiveness measurement | Set difference between code-context.json file list and git diff file list | Token-level tracking, agent reasoning analysis, manual annotation | Set difference on file lists is simple, deterministic, and captures the primary signal: was the file provided or not? Token-level tracking would measure waste more precisely but requires instrumenting the agent's attention, which isn't feasible. File-level granularity is sufficient for Layer 2 tuning. |
| Extraction trigger | Interactive prompt in `speed integrate` (Y/n, default yes) | Automatic (always run), post-hook, separate command only | Interactive prompt keeps the operator in control (P7: additive, never blocking). Default-yes captures data without extra effort. A pure post-hook requires hook infrastructure that doesn't exist. Standalone `speed learn` remains available for manual runs. |
| Timing data source | Wall-clock duration from task JSON timestamps | Model API billing data, turn count, token usage | Task JSON already records start and completion timestamps. Wall-clock duration includes retries, which is the relevant measure for task sizing calibration. Token usage and turn count are useful but available separately in the task JSON without extraction. |
| Unattributed change detection | Git log comparison: feature branch commits vs. task commit SHAs | Diff-based detection, manual flagging | Each task records its commit SHAs. Commits on the feature branch not in any task's commit list are unattributed. Git log comparison is simple and reliable. Diff-based detection would catch amended commits but adds complexity for a rare case. |

## Drawbacks

**LLM cost for review classification (temporary).** Each `speed learn` invocation may make one LLM call per ambiguous review finding until the sklearn classifier activates. For a 5-task feature with 3 findings, that's up to 3 small-model calls. The rule-based fast path reduces this in practice. Once 200+ labeled observations accumulate (approximately 30-40 features), `train_classifier()` produces a local sklearn model and LLM calls drop to zero permanently.

**Git branch must exist at extraction time.** Context effectiveness (step 7) and decomposition quality (step 8) depend on `git diff` against the feature branch. If the branch is deleted before `speed learn` runs, these steps are skipped with a warning. Running extraction as part of `speed integrate` (before cleanup) mitigates this, but manual `speed learn` invocations on old features may produce incomplete observations.

**Pattern matching is conservative.** Requiring 3+ occurrences across features means genuine patterns in the first two features are invisible. A recurring issue across tasks within a single feature won't surface as a pattern until confirmed across features. The threshold prevents false patterns but delays detection.

**Observation log grows without bound.** JSONL files are never pruned by the system. Over hundreds of features, the total observation volume could reach tens of megabytes. Synthesis handles this through staleness detection and recency weighting, but the raw files remain. Manual deletion is the escape hatch. An archival mechanism (move observations older than N features to an archive directory) could be added later if this becomes a real problem.

**Context effectiveness data is unavailable on day one.** Steps 7 (`context_miss`, `context_waste`) depend on `code-context.json`, which Layer 2 writes to `.speed/context/tasks/<id>/context/` during `speed run`. These files do not reliably persist after pipeline completion (the task JSON lacks a `feature` field, so context writes to a global path that is empirically absent post-run). Until `speed run` is modified to copy code-context.json into the feature's `logs/` directory, Steps 7 produces no observations. Step 8 (decomposition quality) is partially affected: it still compares `files_touched` (from task JSON) against the plan's file list, but cannot compare against the code-context file list.

**Guardian data is lossy for large features.** `_run_guardian()` writes JSON log files to `${LOGS_DIR}/guardian-${check_type}-${timestamp}.json`, but `_prune_logs()` (in `lib/gates.sh`) retains only the 3 most recent per check type. For typical features (4-6 tasks), all guardian files survive and Step 3 extracts full structured data (verdicts, scope violations, flags, persona grounding). For features with 8+ tasks, early guardian files are pruned before `speed learn` runs. The task JSON fallback captures rejections only: `task_request_changes()` writes `"GUARDIAN REJECTED: <summary>"` to `review_feedback`, which persists. Aligned and flagged verdicts for pruned files are unrecoverable. A further edge case: if a task is later reviewer-rejected, `task_request_changes` overwrites `review_feedback` with the review JSON, erasing the guardian rejection. Guardian verdict extraction is comprehensive for small features and best-effort for large ones.

**Classification accuracy is unverified on day one.** The rule-based classifier and LLM fallback haven't been tested against real SPEED review findings. Misclassification affects synthesis quality (wrong patterns attributed to wrong categories) but not data integrity. Phase 2's generation-time tagging by the Reviewer will reduce dependence on post-hoc classification.

## Testing Plan

Tests run independently of the SPEED pipeline. No `speed run`, `speed integrate`, or LLM calls required. All tests use synthetic fixtures that mirror real artifact structure. Tests follow the project's existing `check()` pattern (manual pass/fail counting, no pytest dependency).

### Test fixtures

A fixture directory at `tests/fixtures/learn/` contains synthetic artifacts matching the structure of `.speed/features/<name>/`:

```
tests/fixtures/learn/
  feature-clean/                    # 3 tasks, all pass clean
    tasks/1.json
    tasks/2.json
    tasks/3.json
    logs/review-1.json
    logs/review-2.json
    logs/security-audit.json
  feature-messy/                    # retries, guardian rejection, missing files
    tasks/1.json                    # retry_count=2
    tasks/2.json                    # review_feedback="GUARDIAN REJECTED: ..."
    tasks/3.json                    # status=done, clean
    logs/review-1.json
    logs/security-audit.json
    logs/plan-verification.json     # pre-parsed (no markdown wrapping)
    logs/coherence.json             # pre-parsed
  feature-partial/                  # missing artifacts
    tasks/1.json
    # no review, no security, no verify, no coherence
```

Fixtures are committed to the repo. Each fixture file is minimal (only fields the extraction pipeline reads).

### Test files

| File | Scope | Count (est.) |
|------|-------|-------------|
| `tests/test_extract.py` | Extraction pipeline, JSONL I/O, ID determinism | ~35 |
| `tests/test_classify.py` | Classifier stages, training, category accuracy | ~25 |

### test_extract.py coverage

**ID generation:**
- Same inputs produce same ID
- Different detail dicts produce different IDs
- Dict key ordering doesn't affect ID (sort_keys)
- ID format matches `sha256:[a-f0-9]{64}`

**JSONL I/O:**
- Write to new file creates file and parent dirs
- Write N observations, read back N lines, each valid JSON
- Re-write same observations produces 0 new writes (idempotency)
- Corrupt line in existing file is skipped with warning
- Empty file produces empty ID set

**Steps 1-3:** See [Step 1: Task Outcomes](#step-1-task-outcomes), [Step 2: Review Findings](#step-2-review-findings), [Step 3: Guardian Verdicts](#step-3-guardian-verdicts) — test expectations are in each step's section.

**Steps 4-6 — Verify, coherence, security:**
- Verify JSON with drifted requirement produces verify_finding
- Verify JSON with critical_failures produces verify_finding
- Coherence JSON with interface_mismatches produces coherence_issue
- Security JSON with findings produces security_finding per finding
- Missing verify/coherence/security file skips step with warning
- Empty pre-parsed JSON (parsing failed in bash) skips step

**Step 7 — Context effectiveness:**
- Missing code-context.json skips step with warning (day-one behavior)

**Step 8 — Decomposition quality:**
- Task where files_touched matches plan files produces nothing
- Task where files_touched has extras produces decomposition_miss
- Task where files_touched is missing planned files produces decomposition_miss

**Step 9 — Success observations:**
- Clean task (retry=0, no guardian rejection, no findings) produces success
- Task with any issue does NOT produce success (no overlap with Steps 1-8)
- Success detail includes duration, file counts, guardian status

**Step 10 — Pattern detection:**
- Fewer than 3 features of same pattern produces nothing
- 3+ features of same pattern produces pattern_match
- Pattern grouping key uses (type, files_hash, category)

**End-to-end:**
- feature-clean fixture produces only success observations
- feature-messy fixture produces mix of retry, guardian, review, verify, coherence, security observations
- feature-partial fixture produces only task outcomes (Steps 2-6 skipped with warnings)
- Re-running extraction on same fixture produces 0 new observations

### test_classify.py coverage

**Rule-based stage:**
- "missing isinstance check" scores correctness (strong: "missing check")
- "should use the project wrapper" scores convention (strong: "wrapper", "should use")
- "no test for edge case" scores testing (strong: "no test", "edge case")
- "unused import" scores style (strong: "unused import")
- Ambiguous text with no clear winner falls through as inconclusive

**Score thresholds:**
- Score below min_score is inconclusive
- Score at or above min_score but gap below min_gap is inconclusive
- Score at or above min_score and gap at or above min_gap is classified

**sklearn stage (mocked):**
- Model file exists: loaded and predict_proba called
- predict_proba at or above 0.7: category accepted
- predict_proba below 0.7: falls through to LLM
- Model file missing: stage skipped

**LLM stage (mocked):**
- provider_fn returns valid category: accepted
- provider_fn returns invalid string: falls through to unclassified
- provider_fn is None: stage skipped
- provider_fn raises: falls through to unclassified

**train_classifier:**
- Fewer than 200 observations returns False, no model saved
- 200+ observations returns True, model file created
- Model file is loadable by classify()

### Running tests

```bash
# All observation tests (from project root)
python tests/test_extract.py
python tests/test_classify.py

# Quick smoke test against real artifacts (non-destructive, read-only)
./speed learn --feature speed-security --dry-run
```

Tests use only stdlib + scikit-learn (already in `.venv/`). No LLM calls. No git operations (git diff results are hardcoded in fixtures). Prototype file is loaded from `lib/learn/data/review_categories.jsonl`; tests that need custom prototypes create temp `.jsonl` files.

## Implementation Groups

Seven groups, ordered for incremental review. Each produces a testable increment.

| Group | What | Files | Depends on |
|-------|------|-------|-----------|
| 1 | Data model and ID generation | `lib/learn/__init__.py`, `lib/learn/extract.py` (dataclasses, `observation_id`) | Nothing |
| 2 | JSONL I/O | `lib/learn/extract.py` (add `write_observations`) | Group 1 |
| 3 | Classifier | `lib/learn/classify.py` (prototype matching, `REVIEW_PROTOTYPES`, `train_classifier`), `lib/learn/data/review_categories.jsonl` | Nothing |
| 4 | Extraction Steps 1-9 | `lib/learn/extract.py` (add `extract_observations`) | Groups 1, 2, 3 |
| 5 | Pattern detection (Step 10) | `lib/learn/extract.py` (add `detect_patterns`) | Groups 1, 2 |
| 6 | Bash bridge and CLI command | `lib/learn_bridge.sh`, `lib/cmd/learn.sh` | Groups 1-5 |
| 7 | Integration wiring | `speed`, `lib/cmd/integrate.sh`, `.gitignore` | Group 6 |

Groups 1 and 3 can be built in parallel (no dependency). Groups 4 and 5 can be built in parallel after their dependencies land. Group 7 is a 3-line change applied last.

## File Impact

New files:

| File | Purpose |
|------|---------|
| `lib/cmd/learn.sh` | `cmd_learn()` function: flag parsing, dispatch to bridge, summary output |
| `lib/learn_bridge.sh` | Bash-to-Python bridge (sources into orchestrator, follows `context_bridge.sh` pattern) |
| `lib/learn/__init__.py` | Package marker |
| `lib/learn/extract.py` | Extraction pipeline (10 steps), observation ID generation, JSONL I/O, pattern detection |
| `lib/learn/classify.py` | Prototype-based text classifier (TF-IDF → optional embedding cascade → sklearn). Ships with `REVIEW_PROTOTYPES` loaded from `lib/learn/data/review_categories.jsonl`. Includes `train_classifier()` for auto-training. See [Review Finding Classification](#review-finding-classification). |
| `lib/learn/data/review_categories.jsonl` | 67 prototype sentences across 7 categories. Single source of truth for classification. |
| `tests/test_extract.py` | Extraction pipeline tests (per-step, end-to-end, missing artifact handling, ID determinism, JSONL I/O, pattern detection) |
| `tests/test_classify.py` | Classification tests (prototype accuracy, embedding cascade, sklearn integration, prototype loading, auto-training trigger) |

Modified files:

| File | Change |
|------|--------|
| `speed` | Add `learn` to command dispatch: `learn) cmd_learn "$@" ;;` |
| `lib/cmd/integrate.sh` | Add post-integrate prompt calling `cmd_learn` with `||` fallback |
| `.gitignore` | Add `.speed/memory/` |

No changes to any agent prompts, assembly functions, or existing pipeline stages. Observation extraction is purely additive.

## Dependencies

**Existing infrastructure:**

| Dependency | What it provides | Failure behavior |
|------------|-----------------|-----------------|
| `.speed/features/<name>/tasks/<id>.json` | Task outcomes, retry counts, file lists, timing | Skip tasks with missing/malformed JSON. Log error. |
| `.speed/features/<name>/logs/review-<id>.json` | Review findings in free-form text | Skip review step for tasks without review JSON. |
| `.speed/features/<name>/logs/guardian-*.json` | Guardian verdict files with vision alignment, behavioral tests, scope violations, persona grounding, differentiation impact, and flags. Written by `_run_guardian()` at pre-plan, post-review, and post-integration checkpoints. Pruned to 3 per check type by `_prune_logs()`. | Read all surviving files. For features with 4-6 tasks, all files survive. For 8+ tasks, early files are pruned and the fallback source is used. |
| Task JSON `review_feedback` field | Fallback for guardian rejections after pruning. `task_request_changes()` writes `"GUARDIAN REJECTED: <summary>"` when the guardian rejects at `review.sh:292`. | Only captures rejections (not flagged/aligned). If a subsequent reviewer rejection overwrites `review_feedback`, the guardian rejection is lost. Best-effort fallback. |
| `.speed/features/<name>/logs/plan-verification.log` | Spec drift findings, critical failures | Skip verify step entirely. Log note. |
| `.speed/features/<name>/logs/coherence.log` | Interface mismatches, schema inconsistencies | Skip coherence step entirely. Log note. |
| `.speed/features/<name>/logs/security-audit.json` | Security findings by severity and category | Skip security step entirely. Log note. |
| `.speed/context/tasks/<id>/context/code-context.json` | Files provided to each task with tiers. **Note:** these files do not reliably persist. The task JSON lacks a `feature` field, so Layer 2 writes to the global `.speed/context/tasks/` path. These directories are not explicitly cleaned but are empirically absent after pipeline completion. | Skip context effectiveness step (Steps 7-8 context comparisons). Log warning. Produces no `context_miss` or `context_waste` observations. Step 8 decomposition quality still works from task JSON `files_touched` alone. Follow-up: modify `speed run` to copy code-context.json into `.speed/features/<name>/logs/` for persistence. |
| `git` CLI | Branch diffs, commit logs for context and decomposition comparison | Skip context effectiveness and decomposition steps. Log warning. |
| `lib/learn/data/review_categories.jsonl` | Prototype sentences for classification | `_load_prototypes()` raises FileNotFoundError if missing. File ships with the code. |

**New dependency:**

| Package | Purpose | Already installed? |
|---------|---------|-------------------|
| `scikit-learn` | `train_classifier()` uses `TfidfVectorizer` + `SGDClassifier`. `classify()` Stage 2 loads the trained model via `joblib` (bundled with scikit-learn). | Yes (`.venv/`, installed for related spec compression) |

Extraction itself uses stdlib only (json, hashlib, pathlib, os, re). The sklearn dependency is only for the classifier's auto-training and Stage 2 inference, both of which degrade gracefully if sklearn is unavailable (Stage 2 is skipped, training doesn't run). The LLM fallback uses the existing `claude_run()` / provider infrastructure.

## Unresolved Questions

| ID | Question | Impact | Proposed Resolution |
|----|----------|--------|-------------------|
| Q1 | Should `pattern_match` observations include a human-readable summary, or just the structured occurrence list? | Affects whether `speed learn --summary` can display useful pattern descriptions without an LLM call. | Include a `pattern` field with a templated description (e.g., "retry on tasks touching {files} due to {reason}") generated from the shared fields of grouped observations. No LLM needed. |
| Q2 | Should the rule-based classifier keyword lists be configurable via `speed.toml`, or hardcoded? | Configurable rules let projects customize classification. Hardcoded rules are simpler and consistent across projects. | Hardcode for Phase 1. The six categories are general enough. Custom categories are a Phase 2 extension after real-world validation. |

### Resolved Questions

| ID | Question | Resolution |
|----|----------|------------|
| R1 | What fields from review JSON are available for classification? | **Resolved.** Review JSON contains an `issues[]` array with structured fields: `severity`, `file`, `line`, `message`, `suggestion`. Each issue is individually delimited. No segmentation step needed. Classification operates on `message` + `suggestion` per issue. |
| R2 | How should verify and coherence log formats be parsed? | **Resolved.** Both `.log` files contain raw agent output: markdown prose wrapping a fenced JSON code block. The bash bridge pre-parses them via `parse_agent_json` (from `lib/provider.sh`, already used by every agent in the pipeline) and passes clean JSON paths to the Python extraction. No new parsing logic needed. Verify JSON has `spec_requirements[]` (with `status` and `requirement`), `critical_failures[]`, and `semantic_drift[]`. Coherence JSON has `interface_mismatches[]`, `schema_inconsistencies[]`, `missing_connections[]`, and `duplicates[]`. |
| R3 | How does `speed learn` receive the feature name? | **Resolved.** Via `GLOBAL_FEATURE`, the global `--feature` / `-f` flag parsed before subcommand dispatch. Consistent with all other SPEED subcommands. |
