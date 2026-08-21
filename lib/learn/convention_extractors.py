"""Phase A mechanical extractors (A1-A4) for convention discovery.

Each function analyzes a specific signal source (git history, tree-sitter AST,
CSG import graph, lock files) and returns RawPattern objects for downstream
integration and formatting.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections import defaultdict
from pathlib import Path

from lib.learn.conventions import RawPattern

# Shared safety limit for os.walk-based extractors.  Prevents runaway
# traversals on monorepos or projects with vendored dependencies.
_MAX_SOURCE_FILES = 5000

_SKIP_DIRS = frozenset({
    "node_modules", "__pycache__", ".git", "venv", ".venv",
    "dist", "build", ".next", "vendor",
})


# ── A1: Co-modification analysis ─────────────────────────────────────


def _extract_comodification(
    project_root: Path,
    max_commits: int = 2000,
    max_commit_files: int = 50,
) -> list[RawPattern]:
    """Detect file pairs frequently co-modified in git history.

    Parses ``git log --numstat`` to build a co-occurrence matrix. Emits
    symmetric pairs (both files co-modified >= 80% of commits touching
    either) and asymmetric pairs (A always touches B but not vice versa).

    Limits history to *max_commits* (recent commits carry the strongest
    convention signal). Commits touching more than *max_commit_files* are
    skipped — merge commits and bulk renames generate O(n^2) pairs that
    add noise without improving detection.

    Returns empty list when no git history exists or git is unavailable.
    """
    try:
        result = subprocess.run(
            ["git", "log", "--numstat", "--pretty=format:%H",
             f"--max-count={max_commits}"],
            capture_output=True,
            text=True,
            cwd=project_root,
            timeout=30,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return []

    if result.returncode != 0:
        return []

    output = result.stdout.strip()
    if not output:
        return []

    # Parse commits: each commit starts with a SHA line, then blank,
    # then numstat lines (add\tdel\tfile), separated by blank lines.
    commits: list[set[str]] = []
    current_files: set[str] = set()
    in_commit = False

    for line in output.split("\n"):
        stripped = line.strip()
        if not stripped:
            if current_files:
                commits.append(current_files)
                current_files = set()
                in_commit = False
            continue

        # SHA line: 40 hex chars
        if re.match(r"^[0-9a-f]{40}$", stripped):
            if current_files:
                commits.append(current_files)
                current_files = set()
            in_commit = True
            continue

        # Numstat line: added\tremoved\tpath
        if in_commit and "\t" in stripped:
            parts = stripped.split("\t")
            if len(parts) >= 3:
                filepath = parts[2]
                if filepath and filepath != "-":
                    current_files.add(filepath)

    if current_files:
        commits.append(current_files)

    if not commits:
        return []

    # Build per-file commit counts and pairwise co-occurrence counts
    file_commit_count: dict[str, int] = defaultdict(int)
    pair_count: dict[tuple[str, str], int] = defaultdict(int)

    for commit_files in commits:
        if len(commit_files) > max_commit_files:
            continue
        files = sorted(commit_files)
        for f in files:
            file_commit_count[f] += 1
        for i, a in enumerate(files):
            for b in files[i + 1:]:
                pair_count[(a, b)] += 1

    patterns: list[RawPattern] = []
    threshold = 0.80

    seen_pairs: set[tuple[str, str]] = set()

    for (a, b), count in pair_count.items():
        total_a = file_commit_count[a]
        total_b = file_commit_count[b]

        # Fraction of commits touching A that also touch B
        ratio_a = count / total_a if total_a > 0 else 0.0
        # Fraction of commits touching B that also touch A
        ratio_b = count / total_b if total_b > 0 else 0.0

        # Symmetric: both directions >= threshold
        if ratio_a >= threshold and ratio_b >= threshold:
            avg = (ratio_a + ratio_b) / 2.0
            scope_a = str(Path(a).parent) if "/" in a else "."
            scope_b = str(Path(b).parent) if "/" in b else "."
            scopes = sorted(set([scope_a, scope_b]))
            patterns.append(RawPattern(
                type="comodification",
                files=[a, b],
                scope=scopes,
                adherence=round(avg, 2),
                evidence=(
                    f"Co-modified in {count}/{max(total_a, total_b)} commits "
                    f"({ratio_a:.0%} of {a}, {ratio_b:.0%} of {b})"
                ),
            ))
            seen_pairs.add((a, b))
            continue

        # Asymmetric: one direction >= threshold, other below
        if ratio_a >= threshold and ratio_b < threshold:
            scope = str(Path(a).parent) if "/" in a else "."
            patterns.append(RawPattern(
                type="comodification_asymmetric",
                files=[a, b],
                scope=[scope],
                adherence=round(ratio_a, 2),
                evidence=(
                    f"{a} always touches {b} ({ratio_a:.0%} of {total_a} commits), "
                    f"but {b} touches {a} only {ratio_b:.0%} of the time"
                ),
            ))
            seen_pairs.add((a, b))

        if ratio_b >= threshold and ratio_a < threshold:
            if (a, b) not in seen_pairs:
                scope = str(Path(b).parent) if "/" in b else "."
                patterns.append(RawPattern(
                    type="comodification_asymmetric",
                    files=[b, a],
                    scope=[scope],
                    adherence=round(ratio_b, 2),
                    evidence=(
                        f"{b} always touches {a} ({ratio_b:.0%} of {total_b} commits), "
                        f"but {a} touches {b} only {ratio_a:.0%} of the time"
                    ),
                ))

    return patterns


# ── A2: Import and naming analysis ───────────────────────────────────


_SNAKE_RE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
_CAMEL_RE = re.compile(r"^[a-z][a-zA-Z0-9]*$")
_PASCAL_RE = re.compile(r"^[A-Z][a-zA-Z0-9]*$")

# Known test framework import modules
_TEST_FRAMEWORKS = {
    "pytest": "pytest",
    "vitest": "vitest",
    "jest": "jest",
    "@jest/globals": "jest",
    "@testing-library/react": "jest",
    "@testing-library/vue": "jest",
    "mocha": "mocha",
    "unittest": "unittest",
}


def _extract_imports_and_naming(
    project_root: Path, csg: dict | None
) -> list[RawPattern]:
    """Detect naming conventions and test frameworks from tree-sitter data.

    Uses the Extractor from treesitter_extract.py for structured import and
    definition data. When CSG is provided, also reads symbol names from
    ``csg['symbols']``.
    """
    patterns: list[RawPattern] = []

    # Collect definitions and references from tree-sitter
    defs_by_dir: dict[str, list[dict]] = defaultdict(list)
    imports_by_dir: dict[str, list[dict]] = defaultdict(list)
    test_framework_hits: dict[str, int] = defaultdict(int)
    test_file_patterns: dict[str, int] = {"prefix": 0, "suffix": 0}

    try:
        from lib.context.treesitter_extract import Extractor
        extractor = Extractor()
        _collect_treesitter_data(
            project_root, extractor, defs_by_dir, imports_by_dir,
            test_framework_hits, test_file_patterns,
        )
    except (ImportError, Exception):
        pass

    # Supplement from CSG symbols if available
    if csg is not None:
        _collect_csg_symbols(csg, defs_by_dir)

    # Emit test framework patterns
    patterns.extend(_detect_test_frameworks(test_framework_hits, project_root))

    # Emit naming patterns per directory
    patterns.extend(_detect_naming_patterns(defs_by_dir))

    # Emit import style patterns per directory
    patterns.extend(_detect_import_style(imports_by_dir))

    # Emit test file naming patterns
    patterns.extend(_detect_test_file_naming(test_file_patterns, project_root))

    return patterns


def _collect_treesitter_data(
    project_root: Path,
    extractor,
    defs_by_dir: dict[str, list[dict]],
    imports_by_dir: dict[str, list[dict]],
    test_framework_hits: dict[str, int],
    test_file_patterns: dict[str, int],
) -> None:
    """Walk source files and collect tree-sitter extraction results."""
    from lib.context.language_registry import registry

    files_seen = 0
    for root, dirs, files in os.walk(project_root):
        dirs[:] = [
            d for d in dirs
            if not d.startswith(".") and d not in _SKIP_DIRS
        ]

        for fname in files:
            abs_path = os.path.join(root, fname)
            rel_path = os.path.relpath(abs_path, project_root)
            ext = os.path.splitext(fname)[1]

            category, language = registry.classify(ext)
            if category != "source" or language is None:
                continue

            if not extractor.can_parse(language):
                continue

            files_seen += 1
            if files_seen > _MAX_SOURCE_FILES:
                return

            try:
                result = extractor.extract_file(abs_path, language, rel_path)
            except Exception:
                continue

            dir_key = str(Path(rel_path).parent)

            # Collect definitions
            for defn in result.definitions:
                defs_by_dir[dir_key].append({
                    "name": defn.name,
                    "kind": defn.kind,
                    "file": rel_path,
                })

            # Collect import references
            for ref in result.references:
                if ref.kind == "import":
                    imports_by_dir[dir_key].append({
                        "module": ref.module or ref.name,
                        "file": rel_path,
                        "is_relative": (
                            (ref.module or "").startswith(".")
                            if ref.module else False
                        ),
                    })
                    # Check for test framework imports
                    mod = ref.module or ref.name
                    for fw_mod, fw_name in _TEST_FRAMEWORKS.items():
                        if mod == fw_mod or mod.startswith(fw_mod + "."):
                            test_framework_hits[fw_name] += 1

            # Track test file naming patterns
            basename = os.path.basename(rel_path)
            stem = os.path.splitext(basename)[0]
            if language == "python":
                if stem.startswith("test_"):
                    test_file_patterns["prefix"] += 1
                elif stem.endswith("_test"):
                    test_file_patterns["suffix"] += 1
            elif language in ("typescript", "tsx", "javascript"):
                if stem.endswith(".test") or stem.endswith(".spec"):
                    test_file_patterns["suffix"] += 1


def _collect_csg_symbols(
    csg: dict, defs_by_dir: dict[str, list[dict]]
) -> None:
    """Add symbol definitions from CSG data."""
    symbols = csg.get("symbols", [])
    if not isinstance(symbols, list):
        return

    for sym in symbols:
        if not isinstance(sym, dict):
            continue
        name = sym.get("name", "")
        kind = sym.get("kind", "function")
        filepath = sym.get("file", "")
        if name and filepath:
            dir_key = str(Path(filepath).parent)
            defs_by_dir[dir_key].append({
                "name": name,
                "kind": kind,
                "file": filepath,
            })


def _detect_test_frameworks(
    hits: dict[str, int], project_root: Path,
) -> list[RawPattern]:
    """Emit test framework detection patterns."""
    if not hits:
        return []

    patterns = []
    for fw_name, count in sorted(hits.items(), key=lambda x: -x[1]):
        patterns.append(RawPattern(
            type="test_framework",
            files=[],
            scope=[str(project_root)],
            adherence=1.0,
            evidence=f"Detected {count} imports of {fw_name}",
        ))

    return patterns


def _detect_naming_patterns(
    defs_by_dir: dict[str, list[dict]],
) -> list[RawPattern]:
    """Detect function naming (snake_case/camelCase) and class naming per directory."""
    patterns = []

    for dir_key, defs in defs_by_dir.items():
        functions = [d for d in defs if d["kind"] in ("function", "method")]
        classes = [d for d in defs if d["kind"] == "class"]

        # Function naming
        if len(functions) >= 5:
            snake_count = sum(1 for f in functions if _SNAKE_RE.match(f["name"]))
            camel_count = sum(1 for f in functions if _CAMEL_RE.match(f["name"]) and not _SNAKE_RE.match(f["name"]))
            total = len(functions)

            snake_ratio = snake_count / total
            camel_ratio = camel_count / total

            files = sorted(set(f["file"] for f in functions))

            if snake_ratio >= 0.70:
                patterns.append(RawPattern(
                    type="naming_snake",
                    files=files,
                    scope=[dir_key],
                    adherence=round(snake_ratio, 2),
                    evidence=f"{snake_count}/{total} functions use snake_case in {dir_key}",
                ))
            elif camel_ratio >= 0.70:
                patterns.append(RawPattern(
                    type="naming_camel",
                    files=files,
                    scope=[dir_key],
                    adherence=round(camel_ratio, 2),
                    evidence=f"{camel_count}/{total} functions use camelCase in {dir_key}",
                ))

        # Class naming
        if len(classes) >= 3:
            pascal_count = sum(1 for c in classes if _PASCAL_RE.match(c["name"]))
            total_classes = len(classes)
            pascal_ratio = pascal_count / total_classes

            class_files = sorted(set(c["file"] for c in classes))

            if pascal_ratio >= 0.70:
                patterns.append(RawPattern(
                    type="naming_pascal",
                    files=class_files,
                    scope=[dir_key],
                    adherence=round(pascal_ratio, 2),
                    evidence=f"{pascal_count}/{total_classes} classes use PascalCase in {dir_key}",
                ))

    return patterns


def _detect_import_style(
    imports_by_dir: dict[str, list[dict]],
) -> list[RawPattern]:
    """Detect relative vs absolute import patterns per directory."""
    patterns = []

    for dir_key, imports in imports_by_dir.items():
        if len(imports) < 5:
            continue

        relative_count = sum(1 for imp in imports if imp["is_relative"])
        absolute_count = len(imports) - relative_count
        total = len(imports)

        files = sorted(set(imp["file"] for imp in imports))
        rel_ratio = relative_count / total
        abs_ratio = absolute_count / total

        if rel_ratio >= 0.70:
            patterns.append(RawPattern(
                type="import_relative",
                files=files,
                scope=[dir_key],
                adherence=round(rel_ratio, 2),
                evidence=f"{relative_count}/{total} imports are relative in {dir_key}",
            ))
        elif abs_ratio >= 0.70:
            patterns.append(RawPattern(
                type="import_absolute",
                files=files,
                scope=[dir_key],
                adherence=round(abs_ratio, 2),
                evidence=f"{absolute_count}/{total} imports are absolute in {dir_key}",
            ))

    return patterns


def _detect_test_file_naming(
    counts: dict[str, int], project_root: Path,
) -> list[RawPattern]:
    """Emit test file naming convention pattern."""
    total = counts["prefix"] + counts["suffix"]
    if total < 3:
        return []

    if counts["prefix"] > counts["suffix"]:
        ratio = counts["prefix"] / total
        if ratio >= 0.70:
            return [RawPattern(
                type="naming_test_prefix",
                files=[],
                scope=[str(project_root)],
                adherence=round(ratio, 2),
                evidence=(
                    f"{counts['prefix']}/{total} test files use test_* prefix pattern"
                ),
            )]
    elif counts["suffix"] > counts["prefix"]:
        ratio = counts["suffix"] / total
        if ratio >= 0.70:
            return [RawPattern(
                type="naming_test_suffix",
                files=[],
                scope=[str(project_root)],
                adherence=round(ratio, 2),
                evidence=(
                    f"{counts['suffix']}/{total} test files use *_test suffix pattern"
                ),
            )]

    return []


# ── A3: Import graph from CSG ────────────────────────────────────────


def _extract_import_graph(
    project_root: Path, csg: dict | None
) -> list[RawPattern]:
    """Detect per-cluster import conventions and hub files from CSG.

    Reads CSG edges (type='imports') and clusters to determine whether each
    cluster follows relative or absolute import conventions. Also detects
    hub files from the CSG Impact layer stability scores.

    Returns empty list when CSG is None.
    """
    if csg is None:
        return []

    patterns: list[RawPattern] = []

    # Extract edges and clusters
    edges = csg.get("edges", [])
    clusters = csg.get("clusters", [])
    impact = csg.get("impact", {})

    if not isinstance(edges, list):
        edges = []
    if not isinstance(clusters, list):
        clusters = []

    # Build cluster membership: file -> cluster_id
    file_to_cluster: dict[str, str] = {}
    cluster_files: dict[str, list[str]] = defaultdict(list)
    for cluster in clusters:
        if not isinstance(cluster, dict):
            continue
        cid = cluster.get("id", "")
        members = cluster.get("members", [])
        if not isinstance(members, list):
            continue
        for member in members:
            if isinstance(member, str):
                file_to_cluster[member] = cid
                cluster_files[cid].append(member)

    # Group import edges by cluster
    cluster_imports: dict[str, list[dict]] = defaultdict(list)
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        if edge.get("type") != "imports":
            continue
        source = edge.get("source", "")
        cid = file_to_cluster.get(source, "")
        if cid:
            cluster_imports[cid].append(edge)

    # Detect per-cluster import conventions
    for cid, import_edges in cluster_imports.items():
        if len(import_edges) < 5:
            continue

        relative_count = 0
        absolute_count = 0
        for edge in import_edges:
            target = edge.get("target", "")
            source = edge.get("source", "")
            label = edge.get("label", "")

            # Heuristic: if import label starts with "." it's relative
            if label.startswith("."):
                relative_count += 1
            elif label:
                absolute_count += 1
            else:
                # Fall back to path comparison
                source_dir = str(Path(source).parent)
                target_dir = str(Path(target).parent)
                if source_dir == target_dir:
                    relative_count += 1
                else:
                    absolute_count += 1

        total = relative_count + absolute_count
        if total < 5:
            continue

        files = cluster_files.get(cid, [])
        rel_ratio = relative_count / total
        abs_ratio = absolute_count / total

        if rel_ratio >= 0.70:
            patterns.append(RawPattern(
                type="import_relative",
                files=sorted(files),
                scope=[cid],
                adherence=round(rel_ratio, 2),
                evidence=(
                    f"Cluster {cid}: {relative_count}/{total} import edges "
                    f"are relative"
                ),
            ))
        elif abs_ratio >= 0.70:
            patterns.append(RawPattern(
                type="import_absolute",
                files=sorted(files),
                scope=[cid],
                adherence=round(abs_ratio, 2),
                evidence=(
                    f"Cluster {cid}: {absolute_count}/{total} import edges "
                    f"are absolute"
                ),
            ))

    # Detect hub files from stability scores
    stability = impact.get("stability", {})
    if isinstance(stability, dict):
        hub_entries = []
        for filepath, score in stability.items():
            if not isinstance(score, (int, float)):
                continue
            # High stability score = many dependents = hub file
            if score >= 0.8:
                hub_entries.append((filepath, score))

        hub_entries.sort(key=lambda x: -x[1])
        for filepath, score in hub_entries[:10]:
            dir_key = str(Path(filepath).parent) if "/" in filepath else "."
            patterns.append(RawPattern(
                type="hub_file",
                files=[filepath],
                scope=[dir_key],
                adherence=round(score, 2),
                evidence=(
                    f"{filepath} has stability score {score:.2f}, "
                    f"indicating a hub with many dependents"
                ),
            ))

    return patterns


# ── A4: Dependency usage ──────────────────────────────────────────────


def _extract_dependency_usage(project_root: Path) -> list[RawPattern]:
    """Build dependency inventory from lock files and detect wrapper modules.

    Reads requirements.txt, pyproject.toml [project.dependencies],
    package.json dependencies/devDependencies, Cargo.toml [dependencies],
    and go.sum. Detects wrapper modules: if file X imports library L and
    other files import X but never L directly, X is a wrapper convention.
    """
    patterns: list[RawPattern] = []

    # Collect declared dependencies from lock/config files
    dependencies: dict[str, str] = {}  # name -> source file
    _parse_requirements_txt(project_root, dependencies)
    _parse_pyproject_toml(project_root, dependencies)
    _parse_package_json(project_root, dependencies)
    _parse_cargo_toml(project_root, dependencies)
    _parse_go_sum(project_root, dependencies)

    if not dependencies:
        return []

    # Detect wrapper modules by analyzing import relationships
    patterns.extend(_detect_wrappers(project_root, dependencies))

    return patterns


def _parse_requirements_txt(
    project_root: Path, deps: dict[str, str]
) -> None:
    """Parse requirements.txt for dependency names."""
    req_path = project_root / "requirements.txt"
    if not req_path.is_file():
        return

    try:
        for line in req_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            # Strip version specifiers, extras, environment markers
            name = re.split(r"[>=<!\[;@\s]", line)[0].strip()
            if name:
                deps[name.lower()] = "requirements.txt"
    except OSError:
        pass


def _parse_pyproject_toml(
    project_root: Path, deps: dict[str, str]
) -> None:
    """Parse pyproject.toml [project.dependencies]."""
    toml_path = project_root / "pyproject.toml"
    if not toml_path.is_file():
        return

    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            return

    try:
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
        for dep_str in data.get("project", {}).get("dependencies", []):
            if isinstance(dep_str, str):
                name = re.split(r"[>=<!\[;@\s]", dep_str)[0].strip()
                if name:
                    deps[name.lower()] = "pyproject.toml"
    except (OSError, Exception):
        pass


def _parse_package_json(
    project_root: Path, deps: dict[str, str]
) -> None:
    """Parse package.json dependencies and devDependencies."""
    pkg_path = project_root / "package.json"
    if not pkg_path.is_file():
        return

    try:
        data = json.loads(pkg_path.read_text(encoding="utf-8"))
        for section in ("dependencies", "devDependencies"):
            section_deps = data.get(section, {})
            if isinstance(section_deps, dict):
                for name in section_deps:
                    deps[name.lower()] = "package.json"
    except (OSError, json.JSONDecodeError):
        pass


def _parse_cargo_toml(
    project_root: Path, deps: dict[str, str]
) -> None:
    """Parse Cargo.toml [dependencies]."""
    cargo_path = project_root / "Cargo.toml"
    if not cargo_path.is_file():
        return

    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            return

    try:
        with open(cargo_path, "rb") as f:
            data = tomllib.load(f)
        for name in data.get("dependencies", {}):
            deps[name.lower()] = "Cargo.toml"
    except (OSError, Exception):
        pass


def _parse_go_sum(
    project_root: Path, deps: dict[str, str]
) -> None:
    """Parse go.sum for module names."""
    go_sum_path = project_root / "go.sum"
    if not go_sum_path.is_file():
        return

    try:
        seen = set()
        for line in go_sum_path.read_text(encoding="utf-8").splitlines():
            parts = line.strip().split()
            if len(parts) >= 2:
                mod = parts[0]
                if mod not in seen:
                    seen.add(mod)
                    deps[mod.lower()] = "go.sum"
    except OSError:
        pass


def _detect_wrappers(
    project_root: Path, dependencies: dict[str, str]
) -> list[RawPattern]:
    """Detect wrapper modules where one file mediates library access.

    A wrapper pattern exists when file X imports library L and other files
    import X but never import L directly.
    """
    # Map: normalized dep name -> set of files importing it directly
    lib_importers: dict[str, set[str]] = defaultdict(set)
    # Map: module path (relative, no ext) -> set of files importing it
    module_importers: dict[str, set[str]] = defaultdict(set)
    # Map: file -> set of libraries it imports
    file_libs: dict[str, set[str]] = defaultdict(set)

    dep_names = set(dependencies.keys())

    try:
        from lib.context.treesitter_extract import Extractor
        from lib.context.language_registry import registry
        extractor = Extractor()
    except (ImportError, Exception):
        return []

    files_seen = 0
    for root_dir, dirs, files in os.walk(project_root):
        dirs[:] = [
            d for d in dirs
            if not d.startswith(".") and d not in _SKIP_DIRS
        ]

        for fname in files:
            abs_path = os.path.join(root_dir, fname)
            rel_path = os.path.relpath(abs_path, project_root)
            ext = os.path.splitext(fname)[1]

            category, language = registry.classify(ext)
            if category != "source" or language is None:
                continue
            if not extractor.can_parse(language):
                continue

            files_seen += 1
            if files_seen > _MAX_SOURCE_FILES:
                break

            try:
                result = extractor.extract_file(abs_path, language, rel_path)
            except Exception:
                continue

            for ref in result.references:
                if ref.kind != "import":
                    continue

                mod = ref.module or ref.name
                if not mod:
                    continue

                # Check if this imports a known dependency
                mod_base = mod.split(".")[0].lower()
                if mod_base in dep_names:
                    lib_importers[mod_base].add(rel_path)
                    file_libs[rel_path].add(mod_base)

                # Track internal module imports (non-relative, non-dep)
                if not mod.startswith(".") and mod_base not in dep_names:
                    module_importers[mod_base].add(rel_path)

    # Identify wrappers: file X imports lib L, and other files import X but
    # never import L directly
    patterns = []
    for filepath, libs in file_libs.items():
        if not libs:
            continue

        # Who imports this file as a module?
        stem = os.path.splitext(filepath)[0].replace("/", ".").replace("\\", ".")
        module_name = stem.split(".")[-1].lower()
        importers_of_file = module_importers.get(module_name, set())

        if len(importers_of_file) < 2:
            continue

        for lib_name in libs:
            # Check: do the importers of this file avoid importing the lib directly?
            direct_importers = lib_importers.get(lib_name, set())
            # Exclude the wrapper file itself
            other_direct = direct_importers - {filepath}

            if not other_direct and len(importers_of_file) >= 2:
                dir_key = str(Path(filepath).parent)
                patterns.append(RawPattern(
                    type="wrapper_module",
                    files=[filepath],
                    scope=[dir_key],
                    adherence=1.0,
                    evidence=(
                        f"{filepath} wraps {lib_name}: "
                        f"{len(importers_of_file)} files import it, "
                        f"none import {lib_name} directly"
                    ),
                ))

    return patterns
