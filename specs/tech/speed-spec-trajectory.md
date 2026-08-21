# RFC: Spec Trajectory

> See [speed-spec-trajectory.md](../product/speed-spec-trajectory.md) for product context.
> Depends on: Feature storage (`.speed/features/`), Observation Infrastructure ([speed-observations.md](speed-observations.md)), CSG (`lib/context/csg.py`), Assembly functions (`lib/context/assembly.py`)

## Basic Example

```bash
# Manual invocation
speed learn --trajectory

# Output:
# Spec trajectory: 7 features analyzed
#   Active areas: 2 (lib/context/, lib/grounding/)
#   Feature shapes: 1 ("Pipeline stage addition", 3 features)
#   Risk accumulation: 1 high (assembly.py), 2 medium
#   Regression zones: 1 (shared.sh)
#   → .speed/memory/learnings/spec-trajectory-learnings.json
```

```python
# Programmatic usage
from lib.learn.spec_trajectory import analyze_trajectory
from pathlib import Path

result = analyze_trajectory(
    features_dir=Path(".speed/features"),
    memory_dir=Path(".speed/memory"),
    project_root=Path("."),
    context_dir=Path(".speed/context"),
)
print(result.summary())
# "7 features analyzed. 2 active areas, 1 shape, 1 high-risk file."
```

## Overview

Spec Trajectory reads completed feature records (contract.json, task JSON, spec-alignment.json, observations) and produces `spec-trajectory-learnings.json` with structured knowledge about project evolution. No LLM calls. The pipeline is deterministic and driven by file metadata, observation aggregation, and git history.

```
.speed/features/
  ├── feature-a/
  │   ├── contract.json      (Architect's plan: tasks, files, boundaries)
  │   ├── tasks/*.json        (execution: retries, duration, files_touched)
  │   ├── state.json          (timestamps, status)
  │   └── spec_path           (link to tech spec)
  ├── feature-b/
  │   └── ...
  └── feature-c/
      └── ...

.speed/memory/observations/*.jsonl
  (retries, coherence issues, verify findings per feature)

.speed/context/spec-alignment.json
  (spec claims → codebase status)

.speed/context/semantic-graph.json
  (CSG: clusters, symbols, edges)
        ↓
   ┌───────────────────────────────────────┐
   │     Spec Trajectory Pipeline          │
   │                                       │
   │  Step 1: Read feature records         │
   │  Step 2: Compute area volatility      │
   │  Step 3: Extract feature shapes       │
   │  Step 4: Spec quality analysis        │
   │  Step 5: Risk accumulation scoring    │
   │  Step 6: Dependency exposure         │
   │  Step 7: Regression zone detection    │
   │  Step 8: Spec gap patterns            │
   │  Step 9: Format per-agent views       │
   │  Step 10: Write output                │
   └──────────────────┬────────────────────┘
                      ↓
   .speed/memory/learnings/
     spec-trajectory-learnings.json
```

## Input Contract

### Feature records

Each completed feature in `.speed/features/<name>/` provides:

| File | Fields used |
|------|------------|
| `contract.json` | `entities[].path`, `entities[].created_by_task`, `entities[].type` (entity provenance catalog) |
| `tasks/<id>.json` | `status`, `retry_count`, `files_touched`, `completed_at`, `started_at`, `error`, `description`, `acceptance_criteria`, `depends_on` |
| `tasks/<id>.json` | `gate_results.checks[]` (per-gate pass/fail with detail fields), `decisions` (agent-reported learnings), `concerns` (agent-reported risks) |
| `tasks/<id>.json` | `review_verdict`, `review_feedback` (reviewer assessment per task) |
| `state.json` | `status` (must be "completed"), `created_at`, `completed_at` |
| `spec_path` | Path to the tech spec file (for spec quality analysis) |

Task duration is computed from `completed_at - started_at` (no `duration_seconds` field exists).

Features with `state.json.status != "completed"` are excluded.

### Feature analysis artifacts

Per-feature artifacts produced by other pipeline stages. All are optional — steps degrade gracefully when absent and fall back to observation data.

| File | Fields used | Used by |
|------|------------|---------|
| `context/cross-task-analysis.json` | `domain_overlap[].cluster`, `domain_overlap[].tasks_touching`, `domain_overlap[].shared_symbols` | Step 3 (feature shapes): cluster-to-task overlap is pre-computed |
| `spec-traceability.json` | `requirements_found`, `covered[].requirement`, `covered[].covered_by`, `uncovered[]` | Steps 4, 8 (spec quality and spec gaps) |
| `logs/review-*.json` | `verdict`, `spec_verification[].satisfied`, `issues[].severity`, `issues[].file` | Step 4 (spec quality): review override rates per area |
| `logs/decomposition-gate.json` | Task boundary validation results | Step 4 (spec quality): planned vs actual decomposition |

### Observations

From `.speed/memory/observations/<feature>.jsonl`:
- `coherence_issue` observations: cross-task conflicts per feature
- `verify_finding` observations: spec drift and missing requirements
- `retry` observations: retries with file and cause data
- `decomposition_miss` observations: planned vs. actual file lists

### CSG (optional)

From `.speed/context/semantic-graph.json`. Pipeline degrades gracefully without it: area grouping falls back to directory paths, dependency exposure (Step 6) is skipped.

- Cluster IDs and file lists (for area-level grouping)
- Symbol count per file (for function growth tracking)
- Edge count per symbol (for dependency exposure)

### Spec alignment (optional)

From `.speed/context/spec-alignment.json`. If absent, Step 4 uses review logs and observations only.

- Claim status: `confirmed`, `missing`, `divergence`
- Claim sections and types

## Output Contract

### spec-trajectory-learnings.json

```json
{
  "generated_at": "2026-03-09T10:00:00Z",
  "features_analyzed": 7,
  "features_hash": "a3b1c9...",
  "window": 5,

  "active_areas": [
    {
      "area": "lib/context/",
      "cluster": "cluster_context_3",
      "features_touched": 6,
      "features_in_window": 5,
      "touch_rate": 0.86,
      "classification": "active",
      "files_modified": ["assembly.py", "code_context.py", "layer2.py", "csg.py"],
      "retry_rate_in_area": 0.33
    }
  ],

  "mature_areas": [
    {
      "area": "lib/toml.py",
      "cluster": "cluster_toml_1",
      "features_touched": 2,
      "last_touched": "feature-3",
      "classification": "mature",
      "note": "Built in feature 1, extended in feature 3. Patterns stable."
    }
  ],

  "feature_shapes": [
    {
      "shape_id": "pipeline-stage",
      "label": "Pipeline stage addition",
      "features": ["speed-review", "speed-coherence", "speed-security"],
      "task_count": {"min": 4, "max": 5, "median": 5},
      "typical_tasks": [
        "cmd module (lib/cmd/)",
        "agent prompt (agents/)",
        "assembly function (lib/context/assembly.py)",
        "wiring and integration",
        "tests"
      ],
      "clusters_touched": ["cluster_cmd_2", "cluster_context_3", "cluster_agents_4"],
      "retry_hotspots": ["assembly task — retries in 2 of 3 features due to missed imports"],
      "total_files": {"min": 12, "max": 18, "median": 15}
    }
  ],

  "decomposition_precedents": [
    {
      "feature": "speed-security",
      "shape_id": "pipeline-stage",
      "tasks": 5,
      "task_boundaries": [
        {"task_id": "1", "files": ["lib/cmd/audit.sh"], "retries": 0},
        {"task_id": "2", "files": ["agents/security-auditor.md"], "retries": 0},
        {"task_id": "3", "files": ["lib/context/assembly.py"], "retries": 2, "failure": "missed imports"},
        {"task_id": "4", "files": ["lib/grounding.sh", "lib/gates.sh"], "retries": 0},
        {"task_id": "5", "files": ["tests/test_security.py"], "retries": 0}
      ],
      "outcome": "completed, 2 retries on assembly task"
    }
  ],

  "spec_quality": [
    {
      "area": "lib/context/",
      "override_rate": 0.6,
      "common_overrides": ["scope too broad", "missing token budget implications"],
      "accurate_sections": ["acceptance criteria", "task descriptions"],
      "unreliable_sections": ["scope definitions", "file lists"]
    },
    {
      "area": "lib/cmd/",
      "override_rate": 0.15,
      "accurate_sections": ["all sections"],
      "unreliable_sections": []
    }
  ],

  "risk_accumulation": [
    {
      "file": "lib/context/assembly.py",
      "features_touched": 6,
      "function_count": 12,
      "gate_failure_rate": 0.33,
      "coherence_issues_recent": 2,
      "last_refactor": null,
      "risk_level": "high",
      "evidence": "Extended by 6 features with no refactor. 12 functions (current). Gate failures in 33% of tasks. Coherence issues in last 2 features."
    }
  ],

  "dependency_exposure": [
    {
      "file": "lib/context/assembly.py",
      "consumer_count": 7,
      "blast_radius": "moderate",
      "note": "7 consumers (current CSG). Touched by 6 features."
    }
  ],

  "regression_zones": [
    {
      "file": "lib/shared.sh",
      "features": ["feature-3", "feature-5", "feature-7"],
      "issue": "Feature 7 partially reverted feature 5's additions (caught by coherence check)",
      "severity": "medium"
    }
  ],

  "spec_gaps": [
    {
      "area": "lib/context/",
      "gap": "Token budget implications never specified in context layer specs",
      "occurrences": 3,
      "features": ["speed-feedback-loop", "speed-security", "speed-defects"]
    }
  ]
}
```

## Pipeline Implementation

### Module: `lib/learn/spec_trajectory.py`

```python
def analyze_trajectory(
    features_dir: Path,
    memory_dir: Path,
    project_root: Path,
    context_dir: Path | None = None,
    window: int = 5,
) -> TrajectoryResult:
    """Run the full spec trajectory pipeline.

    Args:
        features_dir: .speed/features/ — each subdirectory is a feature
        memory_dir: .speed/memory/ — observations and learnings
        project_root: repo root — for git log queries (Step 5: last refactor)
        context_dir: .speed/context/ — csg, spec-alignment (optional)
        window: number of recent features for active/mature classification
    """
    # Step 1: Load all completed feature records + per-feature artifacts
    # FeatureRecord includes: tasks, cross_task_analysis, spec_traceability,
    # review_logs, decomposition_gate (all optional except tasks)
    features = _read_feature_records(features_dir)
    if len(features) < 3:
        return TrajectoryResult.empty()

    # Codebase-level artifacts (optional, derived from context_dir)
    csg = _load_json(context_dir / "semantic-graph.json") if context_dir else None
    spec_alignment = _load_json(context_dir / "spec-alignment.json") if context_dir else None

    # NOTE: filenames (semantic-graph.json, spec-alignment.json, observations/)
    # follow the existing convention where STATE_DIR is the only shared constant
    # and subdirectory paths are derived inline. If config.sh adds constants for
    # these paths, update here.

    # Load all observations in a single pass (shared by Steps 4, 5, 7, 8)
    observations_dir = memory_dir / "observations"
    obs_by_type = _load_all_observations(observations_dir)

    # Step 2: area volatility (uses task files_touched + CSG clusters)
    active, mature, moderate = _compute_volatility(features, csg, window)

    # Step 3: feature shapes (uses cross_task_analysis for cluster overlap,
    # falls back to CSG, falls back to directory grouping)
    shapes = _extract_shapes(features, csg)
    precedents = _build_precedents(features, shapes)

    # Step 4: spec quality (uses review_logs, decomposition_gate,
    # spec_traceability, spec_alignment, observations)
    spec_quality = _analyze_spec_quality(features, spec_alignment, obs_by_type)

    # Step 5: risk scoring (uses gate_results from tasks, CSG symbol counts,
    # coherence observations, git log for last refactor)
    risk = _score_risk_accumulation(features, csg, obs_by_type, project_root, moderate)

    # Step 6: dependency exposure (uses CSG edges for consumer counts)
    deps = _track_dependency_exposure(risk, csg)

    # Step 7: regression zones (uses coherence + verify observations)
    regressions = _detect_regression_zones(features, obs_by_type)

    # Step 8: spec gaps (uses spec_traceability uncovered[], verify observations)
    gaps = _detect_spec_gaps(features, obs_by_type)

    # Step 9: format per-agent views (stored in result, not separate files)
    # Step 10: caller writes result to disk
    return TrajectoryResult(
        active_areas=active,
        mature_areas=mature,
        feature_shapes=shapes,
        decomposition_precedents=precedents,
        spec_quality=spec_quality,
        risk_accumulation=risk,
        dependency_exposure=deps,
        regression_zones=regressions,
        spec_gaps=gaps,
        features_analyzed=len(features),
        features_hash=_compute_hash(features, observations_dir, context_dir),
        window=window,
    )
```

Minimum: 3 completed features. Below that, `TrajectoryResult.empty()` returns a result with zero entries and no hash (signals "not enough data" to callers and the incremental check).

### Step 1: Read feature records

Loads all completed features into memory. This is the data ingestion step — everything downstream reads from the `FeatureRecord` objects returned here, not from disk. Skips in-progress and failed features so trajectory analysis only reflects shipped work. Sorts by completion time so the windowing logic in Steps 2-5 can distinguish recent activity from historical patterns.

```python
def _read_feature_records(features_dir: Path) -> list[FeatureRecord]:
    """Load task JSONs, state.json, and analysis artifacts for all completed features.

    Scans every subdirectory in features_dir. Skips features that are not
    completed (state.json.status != "completed") or have no task JSONs.
    Returns records sorted by completed_at ascending.
    """
    records: list[FeatureRecord] = []

    for feature_dir in sorted(features_dir.iterdir()):
        if not feature_dir.is_dir():
            continue

        # Gate: only completed features
        state = _load_json(feature_dir / "state.json")
        if not state or state.get("status") != "completed":
            continue

        # Tasks (required — skip feature if no tasks dir)
        tasks_dir = feature_dir / "tasks"
        if not tasks_dir.is_dir():
            continue
        tasks: list[TaskRecord] = []
        skipped_tasks = 0
        for task_file in sorted(tasks_dir.glob("*.json")):
            t = _load_json(task_file)
            if not t:
                skipped_tasks += 1
                continue
            tasks.append(TaskRecord(
                task_id=t.get("id", task_file.stem),
                actual_files=t.get("files_touched", []),
                retries=t.get("retry_count", 0) or 0,
                started_at=t.get("started_at"),
                completed_at=t.get("completed_at"),
                gate_failures=[
                    c["name"] for c in (t.get("gate_results", {}).get("checks", []))
                    if c.get("status") == "fail"
                ],
                decisions=t.get("decisions", []) or [],
                concerns=t.get("concerns", []) or [],
                description=t.get("description", ""),
            ))

        # Warn about corrupt task files — a feature with 5 tasks where 3
        # are corrupt silently becomes a 2-task feature, skewing shape matching
        # (wrong task count), risk scoring (fewer files counted), and precedents
        # (incomplete task boundaries).
        if skipped_tasks > 0:
            log_warning(
                f"Feature {feature_dir.name}: skipped {skipped_tasks} corrupt "
                f"task JSON file(s). {len(tasks)} tasks loaded."
            )

        # Spec path (optional)
        spec_path_file = feature_dir / "spec_path"
        spec_path = spec_path_file.read_text().strip() if spec_path_file.exists() else ""

        # Per-feature artifacts (all optional)
        cross_task = _load_json(feature_dir / "context" / "cross-task-analysis.json")
        traceability = _load_json(feature_dir / "spec-traceability.json")
        review_logs = _load_review_logs(feature_dir / "logs")
        decomp_gate = _load_json(feature_dir / "logs" / "decomposition-gate.json")
        contract = _load_json(feature_dir / "contract.json")

        records.append(FeatureRecord(
            name=feature_dir.name,
            completed_at=state.get("completed_at", ""),
            spec_path=spec_path,
            tasks=tasks,
            cross_task_analysis=cross_task,
            spec_traceability=traceability,
            review_logs=review_logs,
            decomposition_gate=decomp_gate,
            contract=contract,
        ))

    # Sort by completion time — recent features form the "window"
    records.sort(key=lambda r: r.completed_at)
    return records


def _load_json(path: Path) -> dict | list | None:
    """Load a JSON file, return None if missing or malformed."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _load_review_logs(logs_dir: Path) -> list[dict]:
    """Load all review-*.json files from a feature's logs directory."""
    if not logs_dir.is_dir():
        return []
    results = []
    for f in sorted(logs_dir.glob("review-*.json")):
        data = _load_json(f)
        if data:
            results.append(data)
    return results
```

Sort features by `state.json.completed_at` ascending. The last N features (controlled by `window` parameter, default 5) are the "recent window" for active/mature classification.

### Step 2: Compute area volatility

Answers "which parts of the codebase are still being actively modified?" Groups files into areas (CSG clusters when available, directory paths otherwise) and classifies each area as active, moderate, or mature based on how many recent features touched it. Active areas with high retry rates flag places where the system consistently struggles. The Architect uses this to scope tasks defensively in volatile areas. The Developer uses it to anticipate adjacent file impacts.

```python
def _compute_volatility(
    features: list[FeatureRecord],
    csg: dict | None,
    window: int,
) -> tuple[list[ActiveArea], list[MatureArea], set[str]]:
    """Classify codebase areas as active, moderate, or mature.

    Groups files into areas (CSG cluster or parent directory), computes
    touch rate within the recent window, and enriches active areas with
    retry rate from task data.

    Returns (active, mature, moderate_area_names). Moderate areas are not
    surfaced to agents directly. Step 5 uses them to boost risk thresholds
    for files in moderately volatile areas.
    """
    # Build file → features mapping from all task records
    file_features: dict[str, set[str]] = defaultdict(set)
    for feature in features:
        for task in feature.tasks:
            for f in task.actual_files:
                file_features[f].add(feature.name)

    # Group files into areas
    # Priority: CSG cluster (if available) → parent directory
    area_files: dict[str, set[str]] = defaultdict(set)
    for filepath in file_features:
        area = _file_to_area(filepath, csg)
        area_files[area].add(filepath)

    # Determine the recent window (last N features by completed_at)
    recent = {f.name for f in features[-window:]}

    active_areas: list[ActiveArea] = []
    mature_areas: list[MatureArea] = []
    moderate_areas: set[str] = set()

    for area, files in sorted(area_files.items()):
        # Which features touched any file in this area?
        area_features = set()
        for f in files:
            area_features |= file_features[f]

        features_in_window = area_features & recent
        touch_rate = len(features_in_window) / window if window > 0 else 0

        # Compute retry rate: fraction of tasks that had any retries.
        # Scoped to the recent window so historical improvements are reflected.
        # This is a 0-1 proportion (tasks_with_retries / total_tasks), not
        # a raw retry count ratio, so it can be safely formatted as a percentage.
        recent_features = {f for f in features if f.name in recent}
        total_tasks = 0
        tasks_with_retries = 0
        for feature in recent_features:
            for task in feature.tasks:
                if set(task.actual_files) & files:
                    total_tasks += 1
                    if task.retries > 0:
                        tasks_with_retries += 1
        retry_rate = tasks_with_retries / total_tasks if total_tasks > 0 else 0

        # Find CSG cluster name if available
        cluster = _area_to_cluster(area, csg)

        if touch_rate >= 0.5:
            active_areas.append(ActiveArea(
                area=area,
                cluster=cluster,
                features_touched=len(area_features),
                features_in_window=len(features_in_window),
                touch_rate=round(touch_rate, 2),
                classification="active",
                files_modified=sorted(files),
                retry_rate=round(retry_rate, 2),
            ))
        elif touch_rate < 0.2 or _features_since_last_touch(area_features, features) > 3:
            last_feature = _last_feature_touching(area_features, features)
            mature_areas.append(MatureArea(
                area=area,
                cluster=cluster,
                features_touched=len(area_features),
                last_touched=last_feature,
                classification="mature",
                note=_build_mature_note(area_features, features, last_feature),
            ))
        else:
            # 0.2-0.49 = moderate: not surfaced to agents. Passed to
            # Step 5 as a risk threshold boost for files in these areas.
            moderate_areas.add(area)

    return active_areas, mature_areas, moderate_areas


def _file_to_area(filepath: str, csg: dict | None) -> str:
    """Map a file to its area. Use CSG cluster if available, else parent dir."""
    if csg:
        for cluster in csg.get("clusters", []):
            if filepath in cluster.get("files", []):
                return cluster.get("id", os.path.dirname(filepath))
    return os.path.dirname(filepath) or "."
```

Area classification within the recent window:

| Touch rate (features touching area / window size) | Classification |
|---------------------------------------------------|---------------|
| >= 0.5 (modified in 50%+ of recent features) | `active` |
| 0.2-0.49 | `moderate` (not surfaced unless risk accumulation is also present) |
| < 0.2, or last touched > 3 features ago | `mature` |

Active areas include the retry rate for tasks in that area (computed from task records). High volatility + high retry rate = "the system struggles with this area" signal.

### Step 3: Extract feature shapes

Answers "what recurring feature patterns exist in this project?" Groups features by structural similarity (task count, cluster overlap, directory patterns) into named shapes like "Pipeline stage addition" or "Learning subsystem." Each shape becomes a decomposition template for the Architect: when a new feature matches a known shape, the Architect can reference how prior features in that shape were decomposed, which tasks caused retries, and how many files were involved. Features that don't match any shape are stored but not surfaced until a second match appears.

```python
def _extract_shapes(features: list[FeatureRecord], csg: dict | None) -> list[FeatureShape]:
    """Group features by structural similarity into shape taxonomy.

    Computes a fingerprint per feature, groups by fuzzy match,
    and derives labels from directory patterns.
    """
    # Step 1: Compute fingerprint per feature
    # Sort by name for deterministic grouping (iteration order affects
    # which group a feature joins when it could match multiple groups)
    fingerprints: list[tuple[str, _Fingerprint]] = []
    for feature in sorted(features, key=lambda f: f.name):
        fp = _compute_fingerprint(feature, csg)
        fingerprints.append((feature.name, fp))

    # Step 2: Group by fuzzy similarity
    groups: list[list[str]] = []    # each group is a list of feature names
    assigned: set[str] = set()

    for i, (name_a, fp_a) in enumerate(fingerprints):
        if name_a in assigned:
            continue
        group = [name_a]
        assigned.add(name_a)
        for j, (name_b, fp_b) in enumerate(fingerprints):
            if j <= i or name_b in assigned:
                continue
            if _fingerprints_match(fp_a, fp_b):
                group.append(name_b)
                assigned.add(name_b)
        groups.append(group)

    # Step 3: Build FeatureShape for groups with 2+ members
    # Pass pre-computed fingerprints to avoid recomputing in _build_shape
    fp_by_name = dict(fingerprints)
    shapes: list[FeatureShape] = []
    for group in groups:
        if len(group) < 2:
            continue  # single-occurrence, not surfaced
        group_features = [f for f in features if f.name in group]
        group_fps = {f.name: fp_by_name[f.name] for f in group_features}
        shapes.append(_build_shape(group_features, group_fps))

    return shapes


@dataclass
class _Fingerprint:
    task_count: int
    clusters: set[str]          # CSG clusters or directory prefixes
    dir_prefixes: set[str]      # top-level directory prefixes touched
    cluster_source: str         # "cross_task" | "csg" | "directory" — for consistency check


def _compute_fingerprint(feature: FeatureRecord, csg: dict | None) -> _Fingerprint:
    """Compute structural fingerprint for a feature."""
    all_files: set[str] = set()
    for task in feature.tasks:
        all_files.update(task.actual_files)

    # Clusters: prefer cross_task_analysis, fall back to CSG, fall back to dirs
    # Track which source was used so _fingerprints_match can require
    # both features used the same fallback path (prevents non-deterministic
    # grouping when CSG availability changes between features).
    clusters: set[str] = set()
    cluster_source = "directory"
    if feature.cross_task_analysis:
        cluster_source = "cross_task"
        for overlap in feature.cross_task_analysis.get("domain_overlap", []):
            clusters.add(overlap.get("cluster", ""))
    elif csg:
        cluster_source = "csg"
        for f in all_files:
            clusters.add(_file_to_area(f, csg))
    else:
        for f in all_files:
            clusters.add(os.path.dirname(f) or ".")

    # Directory prefixes: first two path components (e.g., "lib/cmd")
    dir_prefixes: set[str] = set()
    for f in all_files:
        parts = Path(f).parts[:2]
        if parts:
            dir_prefixes.add(str(Path(*parts)))

    return _Fingerprint(
        task_count=len(feature.tasks),
        clusters=clusters,
        dir_prefixes=dir_prefixes,
        cluster_source=cluster_source,
    )


def _fingerprints_match(a: _Fingerprint, b: _Fingerprint) -> bool:
    """Fuzzy match: task count +/- 1, structural overlap >= 50%.

    When both features have the same cluster source (both CSG, both directory),
    compare clusters directly. When sources differ (e.g., early features used
    directory grouping, later features have CSG), fall back to dir_prefixes,
    which are always computed regardless of CSG availability. This prevents
    cross-era features from being silently incomparable.
    """
    if abs(a.task_count - b.task_count) > 1:
        return False
    # When cluster sources match, compare clusters (higher fidelity).
    # When they differ, compare dir_prefixes (always available).
    if a.cluster_source == b.cluster_source:
        compare_a, compare_b = a.clusters, b.clusters
    else:
        compare_a, compare_b = a.dir_prefixes, b.dir_prefixes
    if not compare_a or not compare_b:
        return False
    overlap = len(compare_a & compare_b)
    union = len(compare_a | compare_b)
    return (overlap / union) >= 0.5 if union > 0 else False


def _build_shape(
    group_features: list[FeatureRecord],
    fingerprints: dict[str, _Fingerprint],
) -> FeatureShape:
    """Build a FeatureShape from a group of similar features.

    Takes pre-computed fingerprints (from _extract_shapes) to avoid
    redundant recomputation of cluster assignments.
    """
    task_counts = [len(f.tasks) for f in group_features]

    # Typical tasks: collect descriptions, group by directory prefix,
    # take the most common pattern per prefix
    all_dir_prefixes: Counter[str] = Counter()
    for f in group_features:
        for t in f.tasks:
            for path in t.actual_files:
                parts = Path(path).parts[:2]
                if parts:
                    all_dir_prefixes[str(Path(*parts))] += 1

    # Clusters touched (union across group, from pre-computed fingerprints)
    all_clusters: set[str] = set()
    for f in group_features:
        fp = fingerprints[f.name]
        all_clusters |= fp.clusters

    # Retry hotspots: files with retries > 0 in 2+ features
    retry_files: Counter[str] = Counter()
    for f in group_features:
        for t in f.tasks:
            if t.retries > 0:
                for path in t.actual_files:
                    retry_files[path] += 1
    hotspots = [f"{path} — retries in {count} of {len(group_features)} features"
                for path, count in retry_files.most_common(3) if count >= 2]

    # Total files per feature
    file_counts = [
        sum(len(t.actual_files) for t in f.tasks)
        for f in group_features
    ]

    return FeatureShape(
        shape_id=_derive_shape_id(all_dir_prefixes),
        label=_derive_label(all_dir_prefixes),
        features=[f.name for f in group_features],
        task_count_range=(min(task_counts), max(task_counts),
                          sorted(task_counts)[len(task_counts) // 2]),
        typical_tasks=[prefix for prefix, _ in all_dir_prefixes.most_common(5)],
        clusters_touched=sorted(all_clusters),
        retry_hotspots=hotspots,
    )


# ── Shape label derivation (rule-based, no LLM) ──────────────
# Label table maps directory-prefix sets to human-readable labels.
# These are seeded from SPEED's own feature history. For other projects,
# the fallback (joining top directory prefixes) produces reasonable labels.
# Future: derive label table from completed features automatically.

_LABEL_TABLE = [
    ({"lib/cmd", "agents", "lib/context"}, "Pipeline stage addition"),
    ({"lib/learn", "tests"},               "Learning subsystem"),
    ({"dashboard", "lib/cmd"},             "Dashboard feature"),
]

def _derive_label(dir_counts: Counter) -> str:
    """Match directory prefixes against known patterns, fall back to join."""
    top_dirs = {d.split("/")[0] if "/" in d else d for d, _ in dir_counts.most_common(5)}
    for pattern_dirs, label in _LABEL_TABLE:
        if pattern_dirs <= top_dirs:
            return label
    # Fallback: join two most common prefixes
    top_two = [d for d, _ in dir_counts.most_common(2)]
    return " + ".join(top_two) if top_two else "unknown"


def _derive_shape_id(dir_counts: Counter) -> str:
    """Stable ID from sorted top directory prefixes."""
    top = sorted(d for d, _ in dir_counts.most_common(3))
    return "-".join(top).replace("/", "-").replace(".", "") or "unknown"


def _build_precedents(
    features: list[FeatureRecord],
    shapes: list[FeatureShape],
) -> list[DecompositionPrecedent]:
    """Build per-feature task boundary records for each shape.

    For each feature that belongs to a shape, record its exact task
    decomposition: which files each task touched, how many retries,
    and what gate failures occurred. The Architect uses these as
    templates for decomposing similar future features.
    """
    # Index features by name for lookup
    by_name = {f.name: f for f in features}

    precedents: list[DecompositionPrecedent] = []
    for shape in shapes:
        for feature_name in shape.features:
            feature = by_name.get(feature_name)
            if not feature:
                continue

            # Build task boundaries
            total_retries = 0
            boundaries: list[dict] = []
            for task in feature.tasks:
                entry: dict = {
                    "task_id": task.task_id,
                    "files": task.actual_files,
                    "retries": task.retries,
                }
                if task.retries > 0 and task.gate_failures:
                    entry["failure"] = ", ".join(task.gate_failures)
                total_retries += task.retries
                boundaries.append(entry)

            # Outcome summary
            if total_retries == 0:
                outcome = "completed cleanly"
            else:
                # Find the task(s) that caused retries
                retry_tasks = [b for b in boundaries if b["retries"] > 0]
                retry_desc = ", ".join(
                    f"{b['retries']} retries on task {b['task_id']}"
                    for b in retry_tasks
                )
                outcome = f"completed, {retry_desc}"

            precedents.append(DecompositionPrecedent(
                feature=feature_name,
                shape_id=shape.shape_id,
                tasks=len(feature.tasks),
                task_boundaries=boundaries,
                outcome=outcome,
            ))

    return precedents
```

### Step 4: Spec quality analysis

Answers "which areas of the codebase have reliable specs, and which don't?" Aggregates four signals (review verdicts, decomposition gate failures, traceability gaps, verify findings) to compute per-area override rates. An area where specs are overridden 60% of the time tells the Architect to plan defensively there — pad scope, expect undeclared files, add buffer tasks. An area where specs are accurate 95% of the time tells the Architect to trust the spec and scope tightly. The Reviewer uses unreliable section data to focus review effort where specs historically drift.

```python
def _analyze_spec_quality(
    features: list[FeatureRecord],
    spec_alignment: dict | None,
    obs_by_type: dict[str, list[dict]],
) -> list[AreaSpecQuality]:
    """Track spec override rates and accuracy by codebase area.

    Aggregates four signals: review verdicts, decomposition gate results,
    spec traceability gaps, and verify findings. Groups by codebase area
    and computes per-area override rates.
    """
    # Per-area accumulators
    area_stats: dict[str, _AreaStats] = defaultdict(_AreaStats)

    for feature in features:
        # Signal 1: Review override rates (strongest signal)
        # Count ALL reviews in the denominator (not just failures)
        # so override rate reflects the true proportion.
        for review in feature.review_logs:
            verdict = review.get("verdict", "")

            # Denominator: count every review toward every area it touches.
            # For approved reviews, attribute to areas via task files.
            # For rejected reviews, attribute to areas via issue files.
            # Attribute this review to areas via task files.
            # One review = one count per area, regardless of verdict.
            # This keeps the denominator consistent.
            review_areas: set[str] = set()
            for task in feature.tasks:
                for f in task.actual_files:
                    review_areas.add(os.path.dirname(f) or ".")

            for area in review_areas:
                area_stats[area].total_reviews += 1

            if verdict == "approve":
                for sv in review.get("spec_verification", []):
                    if sv.get("satisfied") is True:
                        section = sv.get("spec_section", "unknown")
                        for area in review_areas:
                            area_stats[area].accurate_hits[section] += 1

            elif verdict == "request_changes":
                # Overrides counted per area (not per issue).
                # Multiple issues in the same area = one override.
                override_areas: set[str] = set()
                for issue in review.get("issues", []):
                    filepath = issue.get("file", "")
                    if not filepath:
                        continue
                    area = os.path.dirname(filepath) or "."
                    override_areas.add(area)
                    area_stats[area].override_reasons.append(
                        issue.get("message", "unspecified")
                    )
                for area in override_areas:
                    area_stats[area].overrides += 1

        # Signal 2: Decomposition gate failures
        if feature.decomposition_gate:
            for failure in feature.decomposition_gate.get("failures", []):
                area = failure.get("area", "unknown")
                area_stats[area].override_reasons.append(
                    f"decomposition: {failure.get('reason', 'boundary mismatch')}"
                )
                area_stats[area].overrides += 1
                area_stats[area].total_reviews += 1

        # Signal 3: Spec traceability gaps
        if feature.spec_traceability:
            for uncovered in feature.spec_traceability.get("uncovered", []):
                req = uncovered.get("requirement", "")
                # Attribute to area if we can parse a file path from the requirement
                area = _guess_area_from_requirement(req, feature)
                area_stats[area].uncovered_requirements.append(req)

    # Signal 4: Verify findings from observations
    for obs in obs_by_type.get("verify_finding", []):
        detail = obs.get("detail", {})
        area = os.path.dirname(detail.get("file", "")) or "unknown"
        section = detail.get("spec_section", "unknown")
        area_stats[area].unreliable_hits[section] += 1

    # Build output
    results: list[AreaSpecQuality] = []
    for area, stats in sorted(area_stats.items()):
        override_rate = stats.overrides / stats.total_reviews if stats.total_reviews > 0 else 0
        # Sections that appear 2+ times in accurate_hits and never in unreliable
        accurate = [s for s, c in stats.accurate_hits.items()
                    if c >= 2 and s not in stats.unreliable_hits]
        # Sections that appear 2+ times in unreliable_hits
        unreliable = [s for s, c in stats.unreliable_hits.items() if c >= 2]
        # Deduplicate and take top 3 override reasons
        common = _top_unique(stats.override_reasons, 3)

        if override_rate > 0 or unreliable or common:
            results.append(AreaSpecQuality(
                area=area,
                override_rate=round(override_rate, 2),
                accurate_sections=accurate,
                unreliable_sections=unreliable,
                common_overrides=common,
            ))

    return results


@dataclass
class _AreaStats:
    total_reviews: int = 0
    overrides: int = 0
    override_reasons: list = field(default_factory=list)
    accurate_hits: Counter = field(default_factory=Counter)
    unreliable_hits: Counter = field(default_factory=Counter)
    uncovered_requirements: list = field(default_factory=list)


def _guess_area_from_requirement(req: str, feature: FeatureRecord) -> str:
    """Best-effort: match requirement text against task file paths.

    Scores matches by specificity to avoid false positives from common
    basenames like "test" or "config". Full path match (3) beats directory
    match (2) beats basename match (1, only if basename is 6+ chars to
    filter out generic names). Returns "unknown" if no match scores.
    """
    best_area = "unknown"
    best_score = 0
    for task in feature.tasks:
        for f in task.actual_files:
            score = 0
            if f in req:
                score = 3  # full path match (e.g., "lib/context/assembly.py")
            elif os.path.dirname(f) and os.path.dirname(f) in req:
                score = 2  # directory match (e.g., "lib/context")
            elif len(os.path.basename(f)) >= 6 and os.path.basename(f) in req:
                score = 1  # basename match, but only if specific enough
            if score > best_score:
                best_score = score
                best_area = os.path.dirname(f) or "."
    return best_area


def _load_all_observations(observations_dir: Path) -> dict[str, list[dict]]:
    """Load all observations from all JSONL files in a single pass.

    Returns a dict keyed by observation_type. Callers access specific types
    via obs_by_type.get("coherence_issue", []). The pipeline calls this once
    in analyze_trajectory() and passes the result to Steps 4, 5, 7, and 8,
    avoiding repeated full scans of the observations directory.
    """
    by_type: dict[str, list[dict]] = defaultdict(list)
    if not observations_dir.is_dir():
        return by_type
    for jsonl_file in sorted(observations_dir.glob("*.jsonl")):
        for line in jsonl_file.read_text().splitlines():
            if not line.strip():
                continue
            try:
                obs = json.loads(line)
                obs_type = obs.get("observation_type", "")
                if obs_type:
                    by_type[obs_type].append(obs)
            except json.JSONDecodeError:
                continue
    return by_type


def _top_unique(items: list[str], n: int) -> list[str]:
    """Return top N most common unique strings."""
    return [s for s, _ in Counter(items).most_common(n)]
```

### Step 5: Risk accumulation scoring

Answers "which files are accumulating technical debt?" Scores individual files (not areas) based on how many features have modified them, their gate failure rate, coherence issue trend, and whether they've been refactored. A file touched by 6 features with increasing coherence issues and no refactor is a ticking bomb. The Developer uses high-risk files to write targeted tests for integration points. The Architect uses them to justify refactoring tasks or to avoid piling more work onto already-strained files.

```python
def _score_risk_accumulation(
    features: list[FeatureRecord],
    csg: dict | None,
    obs_by_type: dict[str, list[dict]],
    project_root: Path,
    moderate_areas: set[str] | None = None,
) -> list[RiskAccumulation]:
    """Score per-file risk based on modification frequency, growth, and issue trend.

    Only evaluates files touched by 3+ features. Below that threshold,
    there isn't enough signal to distinguish risk from normal development.

    When moderate_areas is provided (from Step 2), files in moderate areas
    get a +1 boost to their effective feature count for risk thresholds.
    Moderate areas aren't volatile enough to surface on their own, but a
    file in a moderate area with gate failures is riskier than the same
    file in a mature area.
    """
    # Build file → features-touching mapping
    file_features: dict[str, list[str]] = defaultdict(list)
    for feature in features:
        feature_files: set[str] = set()
        for task in feature.tasks:
            feature_files.update(task.actual_files)
        for f in feature_files:
            file_features[f].append(feature.name)

    # Coherence observations (pre-loaded by caller)
    coherence_obs = obs_by_type.get("coherence_issue", [])

    # Build file → coherence issues grouped by feature
    file_coherence: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for obs in coherence_obs:
        detail = obs.get("detail", {})
        for f in detail.get("files", []):
            file_coherence[f][obs.get("feature", "")] += 1

    # Score each file touched by 3+ features
    results: list[RiskAccumulation] = []
    for filepath, touching_features in file_features.items():
        if len(touching_features) < 3:
            continue

        features_touched = len(touching_features)

        # Function count from current CSG (single snapshot)
        function_count = _csg_symbol_count(filepath, csg)

        # Gate failure rate: count tasks that touched this file and had
        # gate failures, across all features
        total_tasks = 0
        failed_tasks = 0
        for feature in features:
            for task in feature.tasks:
                if filepath in task.actual_files:
                    total_tasks += 1
                    if task.gate_failures:
                        failed_tasks += 1
        gate_failure_rate = failed_tasks / total_tasks if total_tasks > 0 else 0

        # Coherence issue trend: does this file have issues in 2+ of
        # the last 3 features? This avoids the ratio trap where a single
        # bad feature with multiple issues triggers "increasing."
        per_feature_counts = file_coherence.get(filepath, {})
        recent_feature_names = {f.name for f in features[-3:]}
        features_with_issues_recent = sum(
            1 for fname, count in per_feature_counts.items()
            if fname in recent_feature_names and count > 0
        )
        coherence_recent = sum(
            per_feature_counts.get(f.name, 0)
            for f in features[-3:]
        )
        coherence_increasing = features_with_issues_recent >= 2

        # Last refactor: git log for "refactor" commits touching this file
        last_refactor = _find_last_refactor(filepath, project_root)

        # Risk level assignment (first match wins, evaluated top-to-bottom)
        # "low" means no active risk signals — not just "has been refactored"
        #
        # effective_touches includes a +1 boost for files in moderate areas
        # (from Step 2). A file touched by 4 features in a moderate area is
        # evaluated as if touched by 5 for threshold purposes.
        file_area = os.path.dirname(filepath) or "."
        moderate_boost = 1 if (moderate_areas and file_area in moderate_areas) else 0
        effective_touches = features_touched + moderate_boost
        has_signals = coherence_increasing or gate_failure_rate > 0.3
        if effective_touches >= 5 and has_signals and last_refactor is None:
            risk_level = "high"
        elif effective_touches >= 5 and has_signals:
            risk_level = "medium"  # signals present but refactored recently
        elif effective_touches >= 3 and has_signals:
            risk_level = "medium"
        else:
            risk_level = "low"  # 3+ features but no coherence/gate signals

        # Build evidence string
        evidence_parts = [f"Touched by {features_touched} features"]
        if function_count is not None:
            evidence_parts.append(f"{function_count} functions (current)")
        if gate_failure_rate > 0:
            evidence_parts.append(f"gate failures in {failed_tasks}/{total_tasks} tasks ({gate_failure_rate:.0%})")
        if coherence_recent > 0:
            evidence_parts.append(f"{coherence_recent} coherence issues in last 3 features")
        if last_refactor:
            evidence_parts.append(f"last refactor: {last_refactor}")
        else:
            evidence_parts.append("no refactor on record")

        results.append(RiskAccumulation(
            file=filepath,
            features_touched=features_touched,
            function_count=function_count,
            gate_failure_rate=round(gate_failure_rate, 2),
            coherence_issues_recent=coherence_recent,
            last_refactor=last_refactor,
            risk_level=risk_level,
            evidence=". ".join(evidence_parts) + ".",
        ))

    # Sort: high risk first, then by features_touched descending
    results.sort(key=lambda r: (
        {"high": 0, "medium": 1, "low": 2}[r.risk_level],
        -r.features_touched,
    ))
    return results


def _csg_symbol_count(filepath: str, csg: dict | None) -> int | None:
    """Count function/class definitions for a file from CSG nodes."""
    if not csg:
        return None
    count = 0
    for node in csg.get("nodes", []):
        if node.get("file") == filepath and node.get("type") in ("function", "class", "method"):
            count += 1
    return count if count > 0 else None


def _find_last_refactor(filepath: str, project_root: Path) -> str | None:
    """Check git log for the most recent structural-change commit touching this file.

    Searches for commits whose message matches any of several refactoring
    patterns: "refactor", "restructure", "reorganize", "split", "extract",
    "simplify". This is a heuristic — commits that restructure a file without
    using any of these words will be missed. The risk scoring table accounts
    for this: a missing refactor signal increases risk level, but the file
    still needs active problem signals (coherence issues or gate failures)
    to reach "high". A false negative here makes the risk assessment slightly
    more conservative, not dangerously wrong.

    Returns the commit date or None.
    """
    # Extended regex matches common refactoring commit patterns.
    # --extended-regexp allows alternation without escaping.
    pattern = "refactor|restructure|reorganize|split|extract|simplify"
    try:
        result = subprocess.run(
            ["git", "log", "--format=%aI", "--extended-regexp",
             "--grep", pattern, "-i", "-1", "--", filepath],
            capture_output=True, text=True, cwd=project_root, timeout=5,
        )
        date = result.stdout.strip()
        return date if date else None
    except (subprocess.TimeoutExpired, OSError):
        return None
```

Risk level assignment (evaluated top-to-bottom, first match wins). Feature count thresholds use `effective_touches`, which adds +1 for files in moderate volatility areas (Step 2). A file touched by 4 features in a moderate area is evaluated at the 5-feature threshold.

| Condition | Level | Meaning |
|-----------|-------|---------|
| 5+ effective touches AND (coherence increasing OR gate failures > 30%) AND no refactor | `high` | Accumulating debt with active problems |
| 5+ effective touches AND (coherence increasing OR gate failures > 30%) AND has refactor | `medium` | Signals present but partially addressed |
| 3+ effective touches AND (coherence increasing OR gate failures > 30%) | `medium` | Active problems, fewer features |
| 3+ effective touches AND no active signals | `low` | Frequently modified but no problems detected |

"Low" means the file is touched often but causes no gate failures and no coherence issues. A recent refactor is not required for "low"; the absence of problems is sufficient.

### Step 6: Dependency exposure

Answers "which high-risk files have the most dependents?" For files flagged as high or medium risk in Step 5, counts how many other files import or call them via CSG edges. Reports the current consumer count and classifies blast radius as high (>10), moderate (5-10), or low (<5). Does not infer trends — CSG is a single snapshot with no historical comparison. The Architect uses high blast radius + high risk to justify splitting large files or adding abstraction boundaries.

```python
def _track_dependency_exposure(
    risk_files: list[RiskAccumulation],
    csg: dict | None,
) -> list[DependencyExposure]:
    """Track consumer counts for high/medium risk files from CSG edges.

    Only processes files already flagged by Step 5. Without CSG, returns
    an empty list (dependency data requires the semantic graph).
    """
    if not csg:
        return []

    # Build reverse edge index: file → set of files that import/call it
    consumers: dict[str, set[str]] = defaultdict(set)
    for edge in csg.get("edges", []):
        source_file = edge.get("source_file", "")
        target_file = edge.get("target_file", "")
        if source_file and target_file and source_file != target_file:
            consumers[target_file].add(source_file)

    results: list[DependencyExposure] = []
    for risk in risk_files:
        if risk.risk_level not in ("high", "medium"):
            continue

        consumer_count = len(consumers.get(risk.file, set()))
        if consumer_count == 0:
            continue  # no dependency data, skip

        # We have a single CSG snapshot. We cannot compute a trend.
        # Report the current consumer count as a fact. The note
        # combines it with feature-touch data so the reader can
        # form their own judgment about blast radius.
        if consumer_count > 10:
            direction = "high"
        elif 5 <= consumer_count <= 10:
            direction = "moderate"
        else:
            direction = "low"

        note_parts = [f"{consumer_count} consumers (current CSG)"]
        if risk.features_touched >= 3:
            note_parts.append(f"touched by {risk.features_touched} features")
        if consumer_count > 10 and risk.features_touched >= 5:
            note_parts.append("high blast radius — modifications ripple widely")

        results.append(DependencyExposure(
            file=risk.file,
            consumer_count=consumer_count,
            blast_radius=direction,
            note=". ".join(note_parts) + ".",
        ))

    # Sort by consumer count descending
    results.sort(key=lambda r: -r.consumer_count)
    return results
```

Consumer count is a point-in-time measurement, not a trend. Tracking actual trends would require storing CSG consumer counts per feature at integration time — a future enhancement.

### Step 7: Regression zone detection

Answers "which files have features stepping on each other?" Aggregates existing coherence issue observations and spec drift findings to identify files where cross-feature conflicts have already been detected by other pipeline stages. Does not perform independent regression detection; silent regressions that escaped the coherence checker and verifier will not appear here. The value is in surfacing patterns across features (file X had conflicts in features 3, 5, and 7) rather than detecting new conflicts. A file that appears in coherence issues across 3+ features is a regression zone. The Reviewer uses these to apply extra scrutiny when reviewing changes to flagged files.

```python
def _detect_regression_zones(
    features: list[FeatureRecord],
    obs_by_type: dict[str, list[dict]],
) -> list[RegressionZone]:
    """Find files where existing observation signals indicate cross-feature conflicts.

    Aggregates two existing signal types: coherence observations (direct
    conflicts caught by the coherence checker) and verify observations
    (spec drift caught by the verifier). Does not perform its own diff
    analysis; if a regression was not caught by coherence or verify checks,
    it will not appear here. A file needs signals across 2+ features to
    qualify.
    """
    # Method 1: Coherence observations — direct cross-feature conflicts
    # Group by file, track which features had issues
    coherence_obs = obs_by_type.get("coherence_issue", [])
    file_conflicts: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    #                     file →      feature → [issue descriptions]

    for obs in coherence_obs:
        detail = obs.get("detail", {})
        feature = obs.get("feature", "")
        issue = detail.get("description", detail.get("issue", "coherence conflict"))
        for f in detail.get("files", []):
            file_conflicts[f][feature].append(issue)

    # Method 2: Verify observations — spec drift on the same section
    # across features implies the area is unstable
    verify_obs = obs_by_type.get("verify_finding", [])
    area_drift: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    #                area →       feature → [drift descriptions]

    for obs in verify_obs:
        detail = obs.get("detail", {})
        if detail.get("finding_type") != "spec_drift":
            continue
        feature = obs.get("feature", "")
        area = os.path.dirname(detail.get("file", "")) or "unknown"
        section = detail.get("spec_section", "unknown section")
        area_drift[area][feature].append(f"spec drift in {section}")

    # Build regression zones from both methods
    zones: dict[str, RegressionZone] = {}  # keyed by file/area

    # From coherence: file-level zones
    for filepath, feature_issues in file_conflicts.items():
        if len(feature_issues) < 2:
            continue  # need 2+ features with conflicts
        feature_names = sorted(feature_issues.keys())
        # Pick the most recent/descriptive issue as the summary
        all_issues = [iss for issues in feature_issues.values() for iss in issues]
        issue_summary = all_issues[-1] if all_issues else "cross-feature conflict"
        severity = "high" if len(feature_names) >= 3 else "medium"

        zones[filepath] = RegressionZone(
            file=filepath,
            features=feature_names,
            issue=issue_summary,
            severity=severity,
        )

    # From verify: area-level zones (only add if not already covered by
    # a more specific file-level zone from coherence)
    for area, feature_drifts in area_drift.items():
        if len(feature_drifts) < 2:
            continue
        # Skip if any file-level zone already covers this area
        if any(z.file.startswith(area) for z in zones.values()):
            continue
        feature_names = sorted(feature_drifts.keys())
        all_drifts = [d for drifts in feature_drifts.values() for d in drifts]
        severity = "high" if len(feature_names) >= 3 else "medium"

        zones[area] = RegressionZone(
            file=area,
            features=feature_names,
            issue=all_drifts[-1] if all_drifts else "recurring spec drift",
            severity=severity,
        )

    # Sort: high severity first, then by number of features descending
    results = sorted(zones.values(), key=lambda r: (
        {"high": 0, "medium": 1, "low": 2}[r.severity],
        -len(r.features),
    ))
    return results
```

### Step 8: Spec gap patterns

Answers "what do specs consistently forget to specify for certain areas?" Finds recurring uncovered requirements and missing spec sections grouped by codebase area. If token budget implications are missing from 3 context-layer specs, that's a pattern the spec writer should address proactively. The Architect uses these to preemptively add sections that specs in a given area historically miss. The spec writer uses them as a checklist when drafting new specs for that area.

```python
def _detect_spec_gaps(
    features: list[FeatureRecord],
    obs_by_type: dict[str, list[dict]],
) -> list[SpecGap]:
    """Find spec sections consistently missing for specific areas.

    Three signals: spec traceability uncovered requirements (primary),
    verify findings with status "missing", and decomposition misses
    where tasks consistently touch more files than planned.
    Requires 2+ occurrences across different features to surface.
    """
    # Accumulate: (area, gap_description) → set of features
    gap_features: dict[tuple[str, str], set[str]] = defaultdict(set)

    # Signal 1 (primary): Spec traceability uncovered requirements
    for feature in features:
        if not feature.spec_traceability:
            continue
        for uncovered in feature.spec_traceability.get("uncovered", []):
            req = uncovered.get("requirement", "")
            if not req:
                continue
            # Attribute to area via task files in this feature
            area = _guess_area_from_requirement(req, feature)
            # Normalize the requirement to a gap description
            gap = _normalize_gap(req)
            gap_features[(area, gap)].add(feature.name)

    # Signal 2: Verify findings with status "missing"
    for obs in obs_by_type.get("verify_finding", []):
        detail = obs.get("detail", {})
        if detail.get("status") != "missing":
            continue
        feature = obs.get("feature", "")
        area = os.path.dirname(detail.get("file", "")) or "unknown"
        section = detail.get("spec_section", "")
        gap = f"missing spec section: {section}" if section else "missing requirement"
        gap_features[(area, gap)].add(feature)

    # Signal 3: Decomposition misses — tasks touching more files than planned
    for obs in obs_by_type.get("decomposition_miss", []):
        detail = obs.get("detail", {})
        feature = obs.get("feature", "")
        extra_files = detail.get("extra_files", [])
        if not extra_files:
            continue
        # Group extra files by area
        area_extras: dict[str, int] = defaultdict(int)
        for f in extra_files:
            area = os.path.dirname(f) or "."
            area_extras[area] += 1
        for area, count in area_extras.items():
            gap = f"file list underestimates scope ({count} undeclared files)"
            gap_features[(area, gap)].add(feature)

    # Filter: 2+ features required to surface
    results: list[SpecGap] = []
    for (area, gap), feature_set in gap_features.items():
        if len(feature_set) < 2:
            continue
        results.append(SpecGap(
            area=area,
            gap=gap,
            occurrences=len(feature_set),
            features=sorted(feature_set),
        ))

    # Sort by occurrences descending
    results.sort(key=lambda r: -r.occurrences)
    return results


def _normalize_gap(requirement: str) -> str:
    """Reduce a requirement string to a reusable gap description.

    Preserves file paths and technical identifiers (these distinguish
    "token budget for assembly.py" from "token budget for csg.py").
    Only strips feature-specific names (feature-xyz-style identifiers)
    and numeric literals (specific thresholds that vary per spec).
    Previous version stripped all quoted and backtick content, causing
    unrelated requirements to collide into the same gap.
    """
    normalized = requirement
    # Strip feature-specific identifiers (e.g., "speed-security", "feature-3")
    normalized = re.sub(r'\b(speed|feature)-[a-z0-9-]+\b', '<feature>', normalized)
    # Strip numeric literals (e.g., "500 tokens", "10 seconds") but keep
    # the unit so "500 tokens" and "10 seconds" don't merge
    normalized = re.sub(r'\b\d+\b', 'N', normalized)
    # Truncate to first 120 chars for grouping (longer than 80 to preserve
    # distinguishing file paths that often appear mid-requirement)
    if len(normalized) > 120:
        normalized = normalized[:117] + "..."
    return normalized.strip()
```

### Step 9: Format per-agent views

Converts the structured trajectory data into agent-specific markdown strings with token budgets. Each agent gets only the sections relevant to their role. The Architect gets the full picture (shapes, precedents, spec quality, risk, all areas) because decomposition decisions need the broadest context. The Developer gets active areas and risk accumulation because those affect implementation choices. The Reviewer gets regression zones because those affect review focus. Truncation drops lowest-signal sections first (spec gaps, dependency exposure) and never truncates active areas or risk accumulation.

```python
# ── Token budget constants ────────────────────────────────
_ARCHITECT_BUDGET = 2000    # tokens
_DEVELOPER_BUDGET = 500
_REVIEWER_BUDGET = 500

# Truncation priority: lowest-signal sections dropped first.
# Active areas and risk accumulation are never truncated.
_ARCHITECT_SECTIONS = [
    # (section_name, formatter, droppable)
    ("active_areas",    _fmt_active_areas,    False),
    ("risk_accumulation", _fmt_risk,          False),
    ("feature_shapes",  _fmt_shapes,          False),
    ("precedents",      _fmt_precedents,      False),
    ("spec_quality",    _fmt_spec_quality,    True),
    ("regression_zones", _fmt_regressions,    True),
    ("dependency_exposure", _fmt_deps,       True),
    ("spec_gaps",       _fmt_gaps,            True),
    ("mature_areas",    _fmt_mature,          True),
]


def _format_for_architect(result: TrajectoryResult) -> str:
    """Full trajectory data within 2,000 token budget.

    Includes: active areas, risk, shapes, precedents, spec quality,
    regressions, dependency exposure, spec gaps, mature areas.
    Truncates by dropping droppable sections from the bottom of
    the priority list until the output fits.
    """
    sections: list[str] = []
    total_tokens = 0

    for name, formatter, droppable in _ARCHITECT_SECTIONS:
        section_md = formatter(result)
        if not section_md:
            continue
        section_tokens = _estimate_tokens(section_md)
        if total_tokens + section_tokens > _ARCHITECT_BUDGET and droppable:
            continue  # drop this section to fit budget
        sections.append(section_md)
        total_tokens += section_tokens

    if not sections:
        return ""
    return "### Project Trajectory\n\n" + "\n\n".join(sections)


def _format_for_developer(result: TrajectoryResult) -> str:
    """Active areas and risk accumulation within 500 token budget.

    The Developer needs to know: which areas are volatile (expect
    adjacent file impacts) and which files are high-risk (write
    targeted tests). Everything else is noise for implementation.
    """
    parts: list[str] = []

    # Risk accumulation (high and medium only)
    high_risk = [r for r in result.risk_accumulation if r.risk_level in ("high", "medium")]
    if high_risk:
        lines = []
        for r in high_risk[:3]:  # top 3
            lines.append(f"- `{r.file}`: {r.risk_level.upper()}. {r.evidence}")
        parts.append("\n".join(lines))

    # Active areas
    if result.active_areas:
        lines = []
        for a in result.active_areas[:3]:  # top 3
            lines.append(f"- `{a.area}`: active ({a.features_touched} features, "
                         f"{a.retry_rate:.0%} retry rate)")
        parts.append("\n".join(lines))

    if not parts:
        return ""

    md = "### Area Volatility\n\n" + "\n\n".join(parts)
    return _truncate_to_budget(md, _DEVELOPER_BUDGET)


def _format_for_reviewer(result: TrajectoryResult) -> str:
    """Regression zones within 500 token budget.

    The Reviewer needs to know: which files have features stepping
    on each other so they can check for unintended reversions.
    """
    if not result.regression_zones:
        return ""

    lines = []
    for z in result.regression_zones[:5]:  # top 5
        features_str = ", ".join(z.features)
        lines.append(f"- `{z.file}`: {features_str}. {z.issue}")

    md = "### Regression Zones\n\n" + "\n".join(lines)
    return _truncate_to_budget(md, _REVIEWER_BUDGET)


# ── Section formatters (used by _format_for_architect) ────

def _fmt_active_areas(result: TrajectoryResult) -> str:
    if not result.active_areas:
        return ""
    lines = ["**Active areas** (modified in 50%+ of recent features):"]
    for a in result.active_areas:
        lines.append(f"- `{a.area}` — {a.features_touched} features, "
                     f"{a.retry_rate:.0%} retry rate")
    return "\n".join(lines)

def _fmt_mature(result: TrajectoryResult) -> str:
    if not result.mature_areas:
        return ""
    lines = ["**Mature areas:**"]
    for m in result.mature_areas[:5]:
        lines.append(f"- `{m.area}` — last touched in {m.last_touched}")
    return "\n".join(lines)

def _fmt_shapes(result: TrajectoryResult) -> str:
    if not result.feature_shapes:
        return ""
    lines = ["**Feature shapes:**"]
    for s in result.feature_shapes:
        hotspot = f" {s.retry_hotspots[0]}" if s.retry_hotspots else ""
        lines.append(f"- \"{s.label}\" ({len(s.features)} features): "
                     f"{s.task_count_range[2]} tasks typical.{hotspot}")
    return "\n".join(lines)

def _fmt_precedents(result: TrajectoryResult) -> str:
    if not result.decomposition_precedents:
        return ""
    lines = ["**Decomposition precedents:**"]
    for p in result.decomposition_precedents[:3]:  # top 3 by shape
        retry_tasks = [b for b in p.task_boundaries if b.get("retries", 0) > 0]
        retry_note = ""
        if retry_tasks:
            retry_note = " Retries: " + ", ".join(
                f"task {b['task_id']} ({b.get('failure', 'unknown')})"
                for b in retry_tasks
            )
        lines.append(f"- {p.feature} ({p.shape_id}): {p.tasks} tasks. {p.outcome}.{retry_note}")
    return "\n".join(lines)

def _fmt_spec_quality(result: TrajectoryResult) -> str:
    if not result.spec_quality:
        return ""
    lines = ["**Spec quality:**"]
    for sq in result.spec_quality:
        if sq.unreliable_sections:
            unreliable = ", ".join(sq.unreliable_sections)
            lines.append(f"- `{sq.area}`: {unreliable} unreliable "
                         f"(overridden {sq.override_rate:.0%})")
        else:
            lines.append(f"- `{sq.area}`: specs accurate ({sq.override_rate:.0%} override rate)")
    return "\n".join(lines)

def _fmt_risk(result: TrajectoryResult) -> str:
    high_risk = [r for r in result.risk_accumulation if r.risk_level in ("high", "medium")]
    if not high_risk:
        return ""
    lines = ["**Risk accumulation:**"]
    for r in high_risk[:5]:
        lines.append(f"- `{r.file}`: {r.risk_level.upper()}. {r.evidence}")
    return "\n".join(lines)

def _fmt_regressions(result: TrajectoryResult) -> str:
    if not result.regression_zones:
        return ""
    lines = ["**Regression zones:**"]
    for z in result.regression_zones[:3]:
        lines.append(f"- `{z.file}`: {', '.join(z.features)}. {z.issue}")
    return "\n".join(lines)

def _fmt_deps(result: TrajectoryResult) -> str:
    if not result.dependency_exposure:
        return ""
    lines = ["**Dependency exposure:**"]
    for d in result.dependency_exposure[:3]:
        lines.append(f"- `{d.file}`: {d.consumer_count} consumers, {d.blast_radius} blast radius")
    return "\n".join(lines)

def _fmt_gaps(result: TrajectoryResult) -> str:
    if not result.spec_gaps:
        return ""
    lines = ["**Spec gaps:**"]
    for g in result.spec_gaps[:3]:
        lines.append(f"- `{g.area}`: {g.gap} ({g.occurrences} features)")
    return "\n".join(lines)


# ── Shared utilities ──────────────────────────────────────

def _estimate_tokens(text: str) -> int:
    """Conservative token estimate: ~3 chars per token.

    Code-heavy text with short identifiers and backtick-wrapped paths
    averages closer to 3 chars/token than 4. Using the lower ratio
    means we overestimate token count, which causes truncation to be
    slightly aggressive. Overestimating is safe (we show less than the
    budget allows). Underestimating is dangerous (we blow the budget
    and get truncated by the assembly function's backstop, which cuts
    from the end without regard to section priority).
    """
    return len(text) // 3

def _truncate_to_budget(md: str, budget: int) -> str:
    """Truncate markdown to fit within a token budget, cutting from the end."""
    tokens = _estimate_tokens(md)
    if tokens <= budget:
        return md
    # Cut at char level (~3 chars/token)
    max_chars = budget * 3
    truncated = md[:max_chars].rsplit("\n", 1)[0]  # cut at line boundary
    return truncated + "\n..."
```

### Step 10: Write output

Writes `spec-trajectory-learnings.json` to the learnings directory. Includes `features_hash` so the next invocation can skip analysis if no new features have completed since the last run. The caller (`analyze_trajectory`) returns the result; the CLI bridge handles the actual file write via `_atomic_write` (same pattern as conventions.json).

```python
def _compute_hash(
    features: list[FeatureRecord],
    observations_dir: Path,
    context_dir: Path | None = None,
) -> str:
    """SHA-256 of feature names + timestamps + observation/context file mtimes.

    Includes modification times for all input files so the hash changes
    when any data source is updated:
    - Observation files: new observations added via speed learn --extract
    - semantic-graph.json: CSG rebuilt (new clusters, edges, symbol counts)
    - spec-alignment.json: claim validation re-run

    Without context file mtimes, a CSG rebuild would not trigger re-analysis,
    serving stale dependency exposure and area grouping data.
    """
    parts = [
        f"{f.name}:{f.completed_at}" for f in sorted(features, key=lambda f: f.name)
    ]
    # Include observation file mtimes
    if observations_dir.is_dir():
        for obs_file in sorted(observations_dir.glob("*.jsonl")):
            mtime = obs_file.stat().st_mtime
            parts.append(f"{obs_file.name}:{mtime}")
    # Include context file mtimes (CSG, spec-alignment)
    if context_dir:
        for ctx_name in ("semantic-graph.json", "spec-alignment.json"):
            ctx_path = context_dir / ctx_name
            if ctx_path.exists():
                parts.append(f"{ctx_name}:{ctx_path.stat().st_mtime}")
    fingerprint = "|".join(parts)
    return hashlib.sha256(fingerprint.encode()).hexdigest()[:16]


def _to_dict(result: TrajectoryResult) -> dict:
    """Serialize TrajectoryResult to a JSON-compatible dict for disk write."""
    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "features_analyzed": result.features_analyzed,
        "features_hash": result.features_hash,
        "window": result.window,
        "active_areas": [asdict(a) for a in result.active_areas],
        "mature_areas": [asdict(m) for m in result.mature_areas],
        "feature_shapes": [
            {**asdict(s), "task_count": {"min": s.task_count_range[0],
                                          "max": s.task_count_range[1],
                                          "median": s.task_count_range[2]}}
            for s in result.feature_shapes
        ],
        "decomposition_precedents": [asdict(p) for p in result.decomposition_precedents],
        "spec_quality": [asdict(q) for q in result.spec_quality],
        "risk_accumulation": [asdict(r) for r in result.risk_accumulation],
        "dependency_exposure": [asdict(d) for d in result.dependency_exposure],
        "regression_zones": [asdict(z) for z in result.regression_zones],
        "spec_gaps": [asdict(g) for g in result.spec_gaps],
        # Per-agent formatted views (pre-rendered for injection)
        "views": {
            "architect": _format_for_architect(result),
            "developer": _format_for_developer(result),
            "reviewer": _format_for_reviewer(result),
        },
    }
```

The CLI bridge calls `_to_dict()` and writes via `_atomic_write` (from `lib/learn/conventions.py`). The `views` dict is pre-rendered so `context_bridge.sh` can read the formatted markdown directly without re-running the formatters.

## Injection

Trajectory data reaches agent prompts through the existing learnings injection path in `context_bridge.sh`. Each agent assembly bridge already loads `{agent}-learnings.json` via `filter_learnings_for_task()` and passes the result as `learnings=`. Trajectory views are appended to that same string.

The views are pre-rendered in `spec-trajectory-learnings.json` under the `views` key (written by Step 10). The injection code reads the view for the target agent and appends it — no formatting logic at injection time.

### Changes to context_bridge.sh

Add a shared helper and call it from each assembly bridge:

```python
def _load_trajectory_view(memory_dir: Path, agent_name: str) -> str:
    """Load pre-rendered trajectory view for an agent. Returns empty string on failure."""
    trajectory_path = memory_dir / "learnings" / "spec-trajectory-learnings.json"
    if not trajectory_path.exists():
        return ""
    try:
        data = json.loads(trajectory_path.read_text())
        return data.get("views", {}).get(agent_name, "")
    except (json.JSONDecodeError, OSError):
        return ""
```

Then in each assembly bridge, after the `learnings = filter_learnings_for_task(...)` line:

```python
# context_assemble_architect (after line 217):
trajectory_md = _load_trajectory_view(memory_dir, "architect")
if trajectory_md:
    pre_len = len(learnings)
    learnings = learnings + "\n\n" + trajectory_md
    log_verbose(f"Trajectory: {_estimate_tokens(trajectory_md)} tokens appended to architect learnings")

# context_assemble_developer (after line 342):
trajectory_md = _load_trajectory_view(memory_dir, "developer")
if trajectory_md:
    learnings = learnings + "\n\n" + trajectory_md
    log_verbose(f"Trajectory: {_estimate_tokens(trajectory_md)} tokens appended to developer learnings")

# context_assemble_reviewer (after line 410):
trajectory_md = _load_trajectory_view(memory_dir, "reviewer")
if trajectory_md:
    learnings = learnings + "\n\n" + trajectory_md
    log_verbose(f"Trajectory: {_estimate_tokens(trajectory_md)} tokens appended to reviewer learnings")
```

### Token budget interaction

The trajectory views are already truncated to their budgets (2,000 / 500 / 500 tokens) during Step 9. The `learnings` string that `filter_learnings_for_task()` produces has its own budget managed by `synthesize.py`. Appending trajectory to learnings may exceed the assembly function's total learnings reserve.

The assembly functions truncate the learnings string via `estimate_tokens_from_text()`. Trajectory is appended last, so it gets cut first when the combined string exceeds the reserve. To prevent trajectory from being silently dead weight:

1. **Logging**: Each injection site logs the trajectory token count at `verbose` level. If trajectory is loaded but never appears in the final prompt, the log shows the mismatch.
2. **Minimum reserve**: The assembly functions should reserve at least 300 tokens for trajectory when trajectory data exists. This means synthesis learnings get truncated to `(reserve - 300)` instead of `reserve`, guaranteeing the Architect always sees at least active areas and risk accumulation (the highest-priority sections that fit in ~300 tokens). Implementation detail for the assembly functions, not this spec.

| Agent | Trajectory budget (pre-truncated) | Total learnings reserve | Truncation behavior |
|-------|-----------------------------------|------------------------|---------------------|
| Architect | 2,000 tokens | 10% of total budget | Assembly truncates from end if combined exceeds reserve |
| Developer | 500 tokens | 10% of total budget | Same — trajectory cut first |
| Reviewer | 500 tokens | 10% of total budget | Same — trajectory cut first |

## CLI Integration

### `speed learn --trajectory`

Standalone invocation:

```bash
# In lib/cmd/learn.sh:
if [[ "$1" == "--trajectory" ]]; then
    learn_trajectory
    return $?
fi
```

Bridge function:

```bash
learn_trajectory() {
    $(_learn_python) <<PYTHON_EOF
import sys, os
sys.path.insert(0, os.environ.get("SPEED_DIR", "."))
from pathlib import Path
from lib.learn.spec_trajectory import analyze_trajectory

project_root = Path(os.environ.get("PROJECT_ROOT", "."))
features_dir = project_root / ".speed" / "features"
memory_dir = project_root / ".speed" / "memory"
context_dir = project_root / ".speed" / "context"

result = analyze_trajectory(features_dir, memory_dir, project_root, context_dir)
print(result.summary())
PYTHON_EOF
}
```

### Automatic trigger

Trajectory analysis runs as part of `speed learn` after observation extraction and synthesis, when 3+ completed features exist.

```
speed learn
  ├── Step 1: Observation extraction
  ├── Step 2: Context tuning aggregation
  ├── Step 3: Synthesis
  └── Step 4: Spec trajectory analysis  ← NEW (if 3+ features)
```

### Incremental

Before analysis, check `spec-trajectory-learnings.json.features_hash`. If no new features completed since last run, skip. Computing the hash is a single directory listing of `.speed/features/` with state.json reads.

## Data Model

```python
@dataclass
class FeatureRecord:
    name: str
    completed_at: str
    spec_path: str
    tasks: list[TaskRecord]
    cross_task_analysis: dict | None    # context/cross-task-analysis.json
    spec_traceability: dict | None      # spec-traceability.json
    review_logs: list[dict]             # logs/review-*.json
    decomposition_gate: dict | None     # logs/decomposition-gate.json
    contract: dict | None               # contract.json (entities)

@dataclass
class TaskRecord:
    task_id: str
    actual_files: list[str]       # from files_touched
    retries: int                   # from retry_count
    started_at: str | None
    completed_at: str | None
    gate_failures: list[str]       # from gate_results.checks[] where status=="fail"
    decisions: list[str]           # agent-reported learnings
    concerns: list[str]            # agent-reported risks
    description: str

@dataclass
class ActiveArea:
    area: str
    cluster: str | None
    features_touched: int
    features_in_window: int         # how many within the recent window
    touch_rate: float
    classification: str             # "active"
    files_modified: list[str]       # files in this area touched across features
    retry_rate: float               # fraction of tasks with retries (0-1 proportion, window-scoped)

@dataclass
class MatureArea:
    area: str
    cluster: str | None
    features_touched: int
    last_touched: str               # feature name
    classification: str             # "mature"
    note: str                       # e.g., "Built in feature 1, extended in feature 3. Patterns stable."

@dataclass
class FeatureShape:
    shape_id: str
    label: str
    features: list[str]
    task_count_range: tuple[int, int, int]  # min, max, median
    typical_tasks: list[str]
    clusters_touched: list[str]
    retry_hotspots: list[str]
    total_files: tuple[int, int, int]  # min, max, median file count across features

@dataclass
class AreaSpecQuality:
    area: str
    override_rate: float
    accurate_sections: list[str]
    unreliable_sections: list[str]
    common_overrides: list[str]

@dataclass
class RiskAccumulation:
    file: str
    features_touched: int
    function_count: int | None      # current CSG symbol count (single snapshot)
    gate_failure_rate: float         # fraction of tasks with gate failures on this file
    coherence_issues_recent: int
    last_refactor: str | None
    risk_level: str  # "high", "medium", "low"
    evidence: str

@dataclass
class DependencyExposure:
    file: str
    consumer_count: int             # current CSG edge count (single snapshot)
    blast_radius: str               # "high" (>10), "moderate" (5-10), "low" (<5)
    note: str                       # human-readable summary

@dataclass
class RegressionZone:
    file: str
    features: list[str]
    issue: str
    severity: str  # "high", "medium", "low"

@dataclass
class DecompositionPrecedent:
    feature: str
    shape_id: str
    tasks: int
    task_boundaries: list[dict]   # [{task_id, files, retries, failure?}]
    outcome: str

@dataclass
class SpecGap:
    area: str
    gap: str
    occurrences: int
    features: list[str]

@dataclass
class TrajectoryResult:
    active_areas: list[ActiveArea]
    mature_areas: list[MatureArea]
    feature_shapes: list[FeatureShape]
    decomposition_precedents: list[DecompositionPrecedent]
    spec_quality: list[AreaSpecQuality]
    risk_accumulation: list[RiskAccumulation]
    dependency_exposure: list[DependencyExposure]
    regression_zones: list[RegressionZone]
    spec_gaps: list[SpecGap]
    features_analyzed: int
    features_hash: str
    window: int                         # the window parameter used for this run

    def summary(self) -> str:
        """Format summary for CLI output."""
```

## File Impact

| File | Change |
|------|--------|
| `lib/learn/spec_trajectory.py` | **New.** Trajectory analysis pipeline (~500 lines estimated) |
| `lib/learn_bridge.sh` | Add `learn_trajectory()` bridge function |
| `lib/cmd/learn.sh` | Add `--trajectory` flag handling. Insert trajectory step into default `speed learn` flow (after synthesis, gated on 3+ features). |
| `lib/context_bridge.sh` | Add trajectory view loading to `context_assemble_architect`, `_developer`, `_reviewer` (read pre-rendered view from `spec-trajectory-learnings.json`, append to existing learnings string) |
| `speed` | Add `--trajectory` to LEARN OPTIONS help text: `"    --trajectory              Run spec trajectory analysis (3+ features required)"` |
| `tests/test_spec_trajectory.py` | **New.** Unit tests for trajectory pipeline |

## Testing Plan

### Unit tests (`tests/test_spec_trajectory.py`)

**Feature reading:**
- Completed features loaded, in-progress features skipped
- Missing contract.json → feature skipped with warning
- Missing task JSON → task skipped, feature still processed
- Features sorted by completed_at

**Volatility:**
- Area touched in 4 of 5 recent features → classified as `active`
- Area touched in 1 of 5 features → classified as `mature`
- Area touched in 3 of 5 → classified as `moderate` (not surfaced unless risk accumulation also present)
- Retry rate computed as fraction of tasks with retries (0-1 proportion), not raw retry count ratio
- Corrupt task JSON files → warning logged, remaining tasks still processed

**Feature shapes:**
- 3 features with 5 tasks each touching same 3 clusters → grouped into one shape
- 2 features with similar structure but task count differs by 2 → not grouped (outside +/- 1 tolerance)
- Single-occurrence feature → stored in unmatched, not surfaced
- Shape label derived from cluster names and task descriptions
- Features with different cluster sources (pre-CSG directory vs post-CSG) → compared via dir_prefixes fallback, still groupable

**Spec quality:**
- Planned 3 files, actual 5 files → override rate 0.4 for that task
- Verify finding with status "missing" → spec gap candidate
- Area with 3+ verify findings → unreliable section identified

**Risk accumulation:**
- File touched by 5 features + coherence in 2+ recent features + no refactor → high risk
- File touched by 5 features + gate failures > 30% + refactored → medium risk
- File touched by 3 features + no coherence issues + low gate failures → low risk

**Dependency exposure:**
- High/medium risk file with >10 CSG consumers → blast_radius "high"
- High/medium risk file with 5-10 consumers → blast_radius "moderate"
- High/medium risk file with <5 consumers → skipped
- Low risk files → not processed (only high/medium risk files checked)
- No CSG available → dependency exposure returns empty list

**Regression zones:**
- File with coherence issues in 2 features → regression zone, severity medium
- File with coherence issues in 3+ features → severity high
- File with no cross-feature issues → not a regression zone

**Spec gaps:**
- Token budget missing from 3 context-layer specs → gap pattern surfaced
- Single missing spec section → not surfaced (below 2-occurrence threshold)

**Formatting:**
- Architect view contains all sections, within 2,000 token budget
- Developer view contains only active areas and risk accumulation, within 500 tokens
- Reviewer view contains only regression zones, within 500 tokens
- Truncation drops lowest-impact sections first

**Incremental:**
- Same features_hash → skip analysis
- New feature completed → full analysis runs
- CSG or spec-alignment rebuilt (mtime changed) → hash changes, full analysis runs
- Fewer than 3 features → empty result, no crash

### Integration tests

- Full pipeline on 3+ synthetic feature records → spec-trajectory-learnings.json produced with all sections
- Assembly functions with trajectory data → sections present in Architect, Developer, Reviewer prompts
- Missing trajectory file → assembly continues without trajectory section
- Fewer than 3 features → no trajectory data produced, no crash

## Validation Criteria

| Check | Expected |
|-------|----------|
| SPEED's own features (7+ completed) produce trajectory data | Active areas, at least 1 feature shape, risk accumulation for assembly.py |
| Active area classification matches reality | `lib/context/` classified as active (modified in most features) |
| Feature shape grouping produces meaningful labels | Pipeline stage features grouped together |
| Spec quality identifies unreliable areas | Context layer specs flagged for scope overrides |
| Risk accumulation flags assembly.py | High risk based on modification frequency and coherence issues |
| Per-agent formatting stays within budget | Architect ≤ 2,000 tokens, Developer ≤ 500, Reviewer ≤ 500 |
| Incremental skip works | Re-run with no new features → skip (sub-millisecond) |
| Graceful degradation | Fewer than 3 features → empty result, no crash, pipeline continues |

## Security & Controls

**Read-only pipeline.** Trajectory reads `.speed/features/*/` metadata and `.speed/memory/observations/*.jsonl`. It does not modify any pipeline state, task JSON, or feature artifacts. The only write is `spec-trajectory-learnings.json` to the learnings directory.

**No external calls.** All data is local. No network requests, no LLM calls, no API access.

**Git access is read-only.** Step 5 runs `git log --extended-regexp --grep 'refactor|restructure|...'` to check for structural-change commits. Read-only, 5-second timeout, failure returns None (not an error).

## Key Decisions

| Decision | Choice | Alternatives Considered | Rationale |
|----------|--------|------------------------|-----------|
| Single-snapshot CSG | Use current CSG only for function counts and consumer counts | Store CSG snapshots per feature at integration time | Per-feature snapshots add storage overhead and integration complexity. Single snapshot covers the common case. Trend inference from feature touch count is adequate. |
| Pre-rendered views | Store formatted markdown in `views` key of output JSON | Re-run formatters at injection time in context_bridge.sh | Avoids importing Python formatters in every assembly call. Views change only when trajectory reruns, not on every agent spawn. |
| Structural shape matching | Task count +/-1, Jaccard overlap >= 50% on clusters (same source) or dir_prefixes (cross-source) | Semantic similarity via spec text embeddings (LLM call) | Deterministic, no LLM cost, matches the "no LLM calls" pipeline principle. Cross-source fallback to dir_prefixes prevents early features (pre-CSG) from being incomparable with later features. |
| Directory-path fallback | Group by parent directory when CSG is unavailable | Require CSG for all grouping | CSG may not exist for early features or cold-start projects. Directory paths are always available and produce reasonable area groupings. |
| 3-feature minimum | Return empty result below 3 completed features | Run with 1-2 features, surface partial data | Below 3 features, "patterns" are just individual data points. Surfacing them as patterns misleads the Architect into treating coincidence as precedent. |

## Drawbacks

- **Pipeline complexity.** 10 steps with 4 optional data sources. More surface area for bugs than simpler analysis pipelines (conventions has 6 steps). Mitigated by: each step is independent and testable in isolation.
- **Stale-by-design.** Trajectory only updates when a new feature completes. During a long feature build, the Architect works with trajectory data that doesn't reflect the current feature's impact. Acceptable because trajectory is about cross-feature patterns, not within-feature state.
- **CSG dependency for full fidelity.** Without CSG, Steps 2, 5, and 6 degrade (directory grouping, no function counts, no consumer counts). Projects that don't build CSG get a noticeably weaker trajectory. Mitigated by: CSG is built by default during `speed plan`.
- **Git log dependency.** Step 5's refactor detection shells out to `git log` with a multi-term regex. In repositories with very large histories, this adds latency (bounded by 5-second timeout per file). Most projects have < 50 high-touch files, so total git time is under 5 seconds. The refactor heuristic catches common patterns but will miss restructuring commits that don't use any of the search terms. The risk scoring compensates: a false negative makes the assessment slightly more conservative (treats file as unrectored), and the file still needs active problem signals to reach "high" risk.
- **Regression detection is signal aggregation, not detection.** Step 7 surfaces patterns from coherence and verify observations. Silent regressions that escaped those checks will not appear. If regression detection coverage is a concern, the fix is to improve the upstream coherence checker, not to add git-diff analysis to trajectory.

## Dependencies

- **Feature storage** (`.speed/features/`) — contract.json, task JSON, state.json, spec_path. Primary data source. Persisted after `speed integrate`.
- **Observation Infrastructure** ([speed-observations.md](speed-observations.md)) — Coherence issues, verify findings, retry observations, decomposition misses. Quality signals that trajectory aggregates.
- **CSG** (`lib/context/csg.py`) — Optional. Cluster structure for area grouping, symbol counts, edge counts.
- **Spec alignment** (`.speed/context/spec-alignment.json`) — Optional. Claim validation status for spec quality analysis.
- **Assembly functions** (`lib/context/assembly.py`) — Injection point. Architect's "Project History", Developer's "Learned Patterns", Reviewer's "Review Calibration" sections.
- **`state.json.status = "completed"`** — Gate for feature inclusion. Requires the `integrate.sh` fix that writes this terminal state (shipped in this session).

## Unresolved Questions

| ID | Question | Impact | Status |
|----|----------|--------|--------|
| Q1 | Should feature shape matching use structural similarity or semantic similarity? | Structural is deterministic but may miss matches. Semantic catches more but needs LLM. | Resolved: structural. RFC specifies task count +/-1, Jaccard cluster overlap >= 50%. |
| Q2 | How many recent features should the active area window consider? | Affects sensitivity. | Resolved: 5 (default), configurable via `window` parameter. |
| Q3 | Should regression detection use git-level diff or observation signals? | Accuracy vs cost. | Resolved: observation signals (coherence issues + verify findings). Git-level analysis deferred. |
