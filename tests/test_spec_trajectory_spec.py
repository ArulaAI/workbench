#!/usr/bin/env python3
"""Tests for specs/tech/speed-spec-trajectory.md internal consistency.

Validates that the pseudocode in the spec is self-consistent: dataclass fields
match constructor calls, function signatures match callers, formatting strings
match field types, etc. These are the 15 adversarial issues identified and fixed.
"""

import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC_DIR = os.path.join(PROJECT_ROOT, "specs", "tech")
PARENT_SPEC = os.path.join(SPEC_DIR, "speed-spec-trajectory.md")

passed = 0
failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name} — {detail}")


# Load the parent spec and all child RFCs.
# After the multi-RFC split, code blocks live in the children.
# The tests validate consistency across the entire RFC family.
spec_parts = []
for fname in sorted(os.listdir(SPEC_DIR)):
    if fname.startswith("speed-spec-trajectory") and fname.endswith(".md"):
        with open(os.path.join(SPEC_DIR, fname)) as f:
            spec_parts.append(f.read())

spec = "\n\n".join(spec_parts)
spec_lines = spec.splitlines()


def find_code_blocks():
    """Extract all fenced code blocks from the spec."""
    blocks = []
    in_block = False
    current = []
    lang = ""
    for line in spec_lines:
        if line.startswith("```") and not in_block:
            in_block = True
            lang = line[3:].strip()
            current = []
        elif line.startswith("```") and in_block:
            blocks.append((lang, "\n".join(current)))
            in_block = False
        elif in_block:
            current.append(line)
    return blocks


code_blocks = find_code_blocks()
python_code = "\n".join(block for lang, block in code_blocks if lang == "python")


# ══════════════════════════════════════════════════════════════
# Fix #1: ActiveArea/MatureArea dataclass-code consistency
# ══════════════════════════════════════════════════════════════

print("\n=== Fix #1: ActiveArea/MatureArea dataclass-code consistency ===")

# Check that the constructor call in _compute_volatility includes all dataclass fields
check(
    "ActiveArea constructor has features_in_window",
    "features_in_window=len(features_in_window)" in python_code,
    "ActiveArea constructed without features_in_window field",
)

check(
    "ActiveArea constructor has classification",
    'classification="active"' in python_code,
    "ActiveArea constructed without classification field",
)

check(
    "ActiveArea constructor has files_modified",
    "files_modified=sorted(files)" in python_code,
    "ActiveArea constructed without files_modified field",
)

check(
    "MatureArea constructor has classification",
    'classification="mature"' in python_code,
    "MatureArea constructed without classification field",
)

check(
    "MatureArea constructor has note",
    "note=_build_mature_note(" in python_code,
    "MatureArea constructed without note field",
)


# ══════════════════════════════════════════════════════════════
# Fix #2: retry_rate is a 0-1 proportion
# ══════════════════════════════════════════════════════════════

print("\n=== Fix #2: retry_rate semantics ===")

check(
    "retry_rate computed as tasks_with_retries / total_tasks",
    "tasks_with_retries / total_tasks" in python_code,
    "retry_rate still uses total_retries / total_tasks",
)

check(
    "retry_rate dataclass comment says 0-1 proportion",
    "fraction of tasks with retries (0-1 proportion" in spec,
    "Dataclass comment still says NOT a 0-1 proportion",
)

# Verify no :.0% format on a non-proportion value
# All :.0% usages should be on retry_rate (which is now 0-1)
format_uses = [line for line in spec_lines if "retry_rate:.0%" in line]
check(
    "retry_rate :.0% format exists (valid for 0-1 proportion)",
    len(format_uses) > 0,
    "No :.0% formatting found for retry_rate",
)


# ══════════════════════════════════════════════════════════════
# Fix #3: Cross-era shape matching
# ══════════════════════════════════════════════════════════════

print("\n=== Fix #3: Cross-era shape matching ===")

check(
    "fingerprints_match falls back to dir_prefixes when sources differ",
    "compare_a, compare_b = a.dir_prefixes, b.dir_prefixes" in python_code,
    "Still refuses to compare across cluster sources",
)

check(
    "fingerprints_match does not hard-reject different sources",
    "a.cluster_source != b.cluster_source" not in python_code
    or "compare_a, compare_b = a.dir_prefixes" in python_code,
    "Still has hard reject for different cluster sources",
)


# ══════════════════════════════════════════════════════════════
# Fix #4: Broader refactor detection
# ══════════════════════════════════════════════════════════════

print("\n=== Fix #4: Refactor detection heuristic ===")

check(
    "git log uses extended-regexp",
    "--extended-regexp" in python_code,
    "Still uses simple --grep=refactor",
)

check(
    "search pattern includes restructure",
    "restructure" in python_code,
    "Pattern does not include restructure",
)

check(
    "search pattern includes split and extract",
    "split" in python_code and "extract" in python_code,
    "Pattern missing split or extract terms",
)


# ══════════════════════════════════════════════════════════════
# Fix #5: Area attribution scoring
# ══════════════════════════════════════════════════════════════

print("\n=== Fix #5: _guess_area_from_requirement scoring ===")

check(
    "uses scored matching (best_score pattern)",
    "best_score" in python_code,
    "Still uses first-match return pattern",
)

check(
    "basename minimum length filter",
    "len(os.path.basename(f)) >= 6" in python_code,
    "No minimum basename length to filter generic names",
)


# ══════════════════════════════════════════════════════════════
# Fix #6: Conservative token estimation
# ══════════════════════════════════════════════════════════════

print("\n=== Fix #6: Token estimation ===")

check(
    "uses 3 chars per token (conservative)",
    "len(text) // 3" in python_code,
    "Still uses len(text) // 4",
)

check(
    "truncation uses 3 chars per token",
    "budget * 3" in python_code,
    "Truncation still uses budget * 4",
)

check(
    "no remaining len(text) // 4 in estimation",
    "len(text) // 4" not in python_code,
    "Still has old 4 chars/token estimate somewhere",
)


# ══════════════════════════════════════════════════════════════
# Fix #7: Single-pass observation loading
# ══════════════════════════════════════════════════════════════

print("\n=== Fix #7: Observation loading ===")

check(
    "_load_all_observations function exists",
    "def _load_all_observations(" in python_code,
    "Single-pass loader not defined",
)

check(
    "returns dict keyed by type",
    "dict[str, list[dict]]" in python_code,
    "Loader does not return dict by type",
)

check(
    "no _load_observations (old per-type loader) references",
    "_load_observations(" not in python_code,
    "Old per-type _load_observations still referenced",
)

check(
    "pipeline calls _load_all_observations once",
    "obs_by_type = _load_all_observations(observations_dir)" in python_code,
    "Pipeline does not call single-pass loader",
)

# Verify steps use obs_by_type.get() not _load_observations()
obs_get_count = python_code.count('obs_by_type.get(')
check(
    "steps use obs_by_type.get() (should be 5+)",
    obs_get_count >= 5,
    f"Only {obs_get_count} uses of obs_by_type.get() found",
)


# ══════════════════════════════════════════════════════════════
# Fix #8: Hash includes CSG and spec-alignment
# ══════════════════════════════════════════════════════════════

print("\n=== Fix #8: Hash completeness ===")

check(
    "_compute_hash accepts context_dir parameter",
    "context_dir: Path | None = None" in python_code
    or "context_dir: Path" in python_code,
    "_compute_hash does not accept context_dir",
)

check(
    "hash includes semantic-graph.json mtime",
    'semantic-graph.json' in python_code
    and "ctx_path.stat().st_mtime" in python_code,
    "Hash does not include CSG file mtime",
)

check(
    "hash includes spec-alignment.json mtime",
    'spec-alignment.json' in python_code
    and "ctx_path.stat().st_mtime" in python_code,
    "Hash does not include spec-alignment file mtime",
)

check(
    "analyze_trajectory passes context_dir to hash",
    "_compute_hash(features, observations_dir, context_dir)" in python_code,
    "Hash call does not include context_dir",
)


# ══════════════════════════════════════════════════════════════
# Fix #9: No redundant fingerprint recomputation
# ══════════════════════════════════════════════════════════════

print("\n=== Fix #9: Fingerprint reuse ===")

check(
    "_build_shape takes fingerprints dict",
    "fingerprints: dict[str, _Fingerprint]" in python_code,
    "_build_shape still takes csg parameter",
)

check(
    "_extract_shapes passes pre-computed fingerprints",
    "fp_by_name = dict(fingerprints)" in python_code,
    "Fingerprints not passed from _extract_shapes to _build_shape",
)

check(
    "_build_shape uses fingerprints[f.name] not _compute_fingerprint",
    "fp = fingerprints[f.name]" in python_code,
    "_build_shape still calls _compute_fingerprint",
)


# ══════════════════════════════════════════════════════════════
# Fix #10: Moderate areas passed to risk scoring
# ══════════════════════════════════════════════════════════════

print("\n=== Fix #10: Moderate areas integration ===")

check(
    "_score_risk_accumulation accepts moderate_areas",
    "moderate_areas: set[str]" in python_code,
    "Risk scoring does not accept moderate_areas parameter",
)

check(
    "pipeline passes moderate to risk scoring",
    "risk = _score_risk_accumulation(features, csg, obs_by_type, project_root, moderate)" in python_code,
    "Pipeline does not pass moderate areas to risk scoring",
)

check(
    "effective_touches computed with moderate boost",
    "effective_touches = features_touched + moderate_boost" in python_code,
    "No moderate area boost in risk scoring",
)

check(
    "risk table uses effective_touches",
    "effective touches" in spec.lower(),
    "Risk level table still uses raw features_touched",
)


# ══════════════════════════════════════════════════════════════
# Fix #11: Precedents in architect view
# ══════════════════════════════════════════════════════════════

print("\n=== Fix #11: Precedents in architect view ===")

check(
    "_fmt_precedents function defined",
    "def _fmt_precedents(" in python_code,
    "No _fmt_precedents formatter",
)

check(
    "precedents in _ARCHITECT_SECTIONS",
    '"precedents"' in python_code,
    "precedents not listed in _ARCHITECT_SECTIONS",
)


# ══════════════════════════════════════════════════════════════
# Fix #12: Regression detection description accuracy
# ══════════════════════════════════════════════════════════════

print("\n=== Fix #12: Regression detection description ===")

check(
    "regression docstring says aggregates existing signals",
    "existing observation signals" in python_code
    or "Aggregates two existing signal types" in python_code,
    "Regression docstring still overpromises independent detection",
)

check(
    "regression step prose mentions signal aggregation",
    "existing observation signals" in spec
    or "Aggregates existing coherence issue observations" in spec
    or "signal aggregation, not independent detection" in spec,
    "Step 7 prose still claims independent detection",
)


# ══════════════════════════════════════════════════════════════
# Fix #13: Gap normalization preserves file identifiers
# ══════════════════════════════════════════════════════════════

print("\n=== Fix #13: Gap normalization ===")

check(
    "normalize_gap preserves file paths (no backtick stripping)",
    '`[^`]*`' not in python_code.split("_normalize_gap")[1].split("def ")[0]
    if "_normalize_gap" in python_code else False,
    "Still strips backtick content (file paths)",
)

check(
    "normalize_gap strips feature identifiers",
    "speed|feature" in python_code,
    "Does not strip feature-specific identifiers",
)

check(
    "normalize_gap uses 120 char limit (not 80)",
    "> 120" in python_code,
    "Still uses 80 char truncation limit",
)


# ══════════════════════════════════════════════════════════════
# Fix #14: Corrupt task warning
# ══════════════════════════════════════════════════════════════

print("\n=== Fix #14: Corrupt task handling ===")

check(
    "skipped_tasks counter exists",
    "skipped_tasks" in python_code,
    "No skipped_tasks tracking variable",
)

check(
    "log_warning called for corrupt tasks",
    "log_warning" in python_code and "skipped" in python_code,
    "No warning logged for corrupt task files",
)


# ══════════════════════════════════════════════════════════════
# Fix #15: Window stored in TrajectoryResult
# ══════════════════════════════════════════════════════════════

print("\n=== Fix #15: Window in TrajectoryResult ===")

check(
    "TrajectoryResult has window field",
    "window: int" in python_code,
    "TrajectoryResult does not have window field",
)

check(
    "_to_dict uses result.window not hardcoded 5",
    "result.window" in python_code,
    "_to_dict still hardcodes window: 5",
)

check(
    "no hardcoded 'window': 5 in _to_dict",
    '"window": 5' not in python_code,
    "_to_dict still has hardcoded window: 5",
)

check(
    "analyze_trajectory passes window to result",
    "window=window," in python_code,
    "analyze_trajectory does not pass window to TrajectoryResult",
)


# ══════════════════════════════════════════════════════════════
# Cross-cutting consistency checks
# ══════════════════════════════════════════════════════════════

print("\n=== Cross-cutting consistency ===")

# No stale references to the old observations_dir parameter in step functions
step_functions = [
    "_analyze_spec_quality",
    "_score_risk_accumulation",
    "_detect_regression_zones",
    "_detect_spec_gaps",
]
for func_name in step_functions:
    # Find the function definition and check its signature
    pattern = f"def {func_name}("
    if pattern in python_code:
        # Get the function signature (up to the closing paren or next line)
        idx = python_code.index(pattern)
        sig_end = python_code.index(")", idx) + 1
        sig = python_code[idx:sig_end]
        check(
            f"{func_name} uses obs_by_type (not observations_dir)",
            "obs_by_type" in sig,
            f"Signature still uses observations_dir: {sig[:100]}",
        )

# Verify the drawbacks section mentions regression detection limitation
check(
    "drawbacks section covers regression detection scope",
    "signal aggregation, not detection" in spec,
    "Drawbacks section does not mention regression detection limitation",
)

# Verify testing plan includes CSG hash test
check(
    "testing plan covers CSG/spec-alignment hash changes",
    "CSG or spec-alignment rebuilt" in spec
    or "CSG or spec-alignment mtime" in spec,
    "Testing plan does not cover hash changes from CSG/spec-alignment",
)

# Verify testing plan covers cross-era shape matching
check(
    "testing plan covers cross-era shape matching",
    "different cluster sources" in spec,
    "Testing plan does not cover cross-era shape matching",
)


# ══════════════════════════════════════════════════════════════
# Foundation adversarial fixes (round 2)
# ══════════════════════════════════════════════════════════════

print("\n=== Foundation adversarial fixes ===")

# Fix AA-1: FeatureShape.total_files populated in _build_shape
check(
    "total_files populated in _build_shape constructor",
    "total_files=(min(file_counts)" in python_code,
    "_build_shape still missing total_files argument",
)

# Fix AA-7: TrajectoryResult.empty() classmethod defined
check(
    "TrajectoryResult.empty() classmethod defined",
    "def empty(cls)" in python_code,
    "TrajectoryResult has no empty() classmethod",
)

check(
    "empty() returns instance with zero features_analyzed",
    "features_analyzed=0" in python_code,
    "empty() does not set features_analyzed=0",
)

# Fix AA-2: _file_to_area uses O(1) index lookup
check(
    "_build_file_cluster_index function defined",
    "def _build_file_cluster_index(" in python_code,
    "No cluster index builder function",
)

check(
    "_file_to_area takes file_cluster_index (not csg)",
    "file_cluster_index: dict[str, str]" in python_code,
    "_file_to_area still takes csg parameter",
)

# Fix AA-3: _load_json rejects arrays
check(
    "_load_json rejects non-dict JSON (isinstance check)",
    "isinstance(data, dict)" in python_code,
    "_load_json still accepts JSON arrays",
)

# Fix AA-6: returns plain dict not defaultdict
check(
    "observation loader returns dict() not defaultdict",
    "return dict(by_type)" in python_code,
    "Still returns raw defaultdict",
)

# Fix AA-11: unrecognized observation type warning
check(
    "observation loader warns on unrecognized types",
    "_KNOWN_OBS_TYPES" in python_code,
    "No known types validation",
)

check(
    "unknown types logged as warning",
    "Unrecognized observation types" in python_code,
    "No warning message for unknown types",
)

# Fix AA-12: _to_dict excludes raw tuple keys
check(
    "_to_dict filters out task_count_range and total_files from asdict",
    'k not in ("task_count_range", "total_files")' in python_code
    or "task_count_range" in python_code.split("_to_dict")[1].split("def ")[0]
    if "_to_dict" in python_code else False,
    "_to_dict still leaks raw tuple keys",
)

# Fix AA-4: truncation handles single-line input
check(
    "_truncate_to_budget handles single-line (word boundary fallback)",
    'rsplit(" ", 1)' in python_code,
    "No word-boundary fallback for single-line truncation",
)

# Fix AA-13: line-by-line JSONL reading
check(
    "observation loader reads line-by-line (open instead of read_text)",
    "with open(jsonl_file)" in python_code
    or "open(jsonl_file) as" in python_code,
    "Still uses read_text().splitlines() for JSONL files",
)

# Fix AA-7: summary() method body defined
check(
    "summary() method has implementation body",
    "features analyzed" in python_code.lower()
    or "self.features_analyzed" in python_code,
    "summary() method body is empty",
)


# ══════════════════════════════════════════════════════════════
# Results
# ══════════════════════════════════════════════════════════════

print("\n" + "═" * 60)
print(f"Results: {passed} passed, {failed} failed")
print()

if failed:
    sys.exit(1)
