#!/usr/bin/env python3
"""
Test Layer 2b: Naming convention matching.

Validates that naming conventions connect story/test files to their components
where TF-IDF and import analysis fail.

Patterns:
  TS/JS stories:  AgencyReviews.stories.tsx  →  agency-reviews.tsx  (PascalCase → kebab-case)
                  BookingForm.stories.tsx    →  BookingForm.tsx      (same name, drop .stories)
                  button.stories.tsx        →  button.tsx           (direct match)

  TS/JS tests:    BookingForm.test.tsx      →  BookingForm.tsx
                  agency-reviews.spec.ts    →  agency-reviews.ts

  Python tests:   test_booking.py           →  booking.py
                  booking_test.py           →  booking.py
"""

import os
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from prototype_clustering_v3 import (
    get_code_files,
    classify_language,
    CODE_EXTENSIONS,
)


def pascal_to_kebab(name: str) -> str:
    """Convert PascalCase/camelCase to kebab-case."""
    # Insert hyphen before each uppercase letter that follows a lowercase
    result = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", name)
    # Insert hyphen between consecutive uppercase and the next lowercase
    result = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1-\2", result)
    return result.lower()


def pascal_to_snake(name: str) -> str:
    """Convert PascalCase/camelCase to snake_case."""
    result = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    result = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", result)
    return result.lower()


def find_naming_convention_edges(
    repo_path: str, files: list[str]
) -> list[tuple[str, str, str]]:
    """
    Match test/story files to their components by naming convention.

    Returns list of (test_or_story_file, component_file, match_type).
    match_type is one of: "exact", "pascal-kebab", "pascal-snake", "prefix-test", "suffix-test"
    """
    # Build lookup: directory → {normalized_name → file_path}
    # Multiple lookups to handle different naming conventions
    dir_files = defaultdict(dict)  # dir → {stem_lower → filepath}
    all_stems = {}  # stem_lower → [filepaths]  (across all dirs)

    for f in files:
        ext = os.path.splitext(f)[1]
        stem = Path(f).stem

        # Skip test/story files in the lookup — they're the source, not the target
        if any(marker in stem.lower() for marker in [".stories", ".story", ".test", ".spec", "test_", "_test"]):
            continue
        # Also skip if the suffix is .stories, .test, .spec (double extension)
        if any(stem.endswith(s) for s in [".stories", ".story", ".test", ".spec"]):
            continue

        parent = os.path.dirname(f)
        stem_lower = stem.lower()
        dir_files[parent][stem_lower] = f

        # Also index by kebab-case and snake_case variants
        kebab = pascal_to_kebab(stem)
        snake = pascal_to_snake(stem)
        if kebab != stem_lower:
            dir_files[parent][kebab] = f
        if snake != stem_lower:
            dir_files[parent][snake] = f

        # Global index for cross-directory matching
        if stem_lower not in all_stems:
            all_stems[stem_lower] = []
        all_stems[stem_lower].append(f)
        if kebab != stem_lower:
            if kebab not in all_stems:
                all_stems[kebab] = []
            all_stems[kebab].append(f)
        if snake != stem_lower:
            if snake not in all_stems:
                all_stems[snake] = []
            all_stems[snake].append(f)

    edges = []

    for f in files:
        stem = Path(f).stem
        ext = os.path.splitext(f)[1]
        parent = os.path.dirname(f)
        lang = classify_language(f)

        # Detect test/story files
        target_name = None
        match_type = None

        # TypeScript/JS patterns
        if lang == "typescript":
            # file.stories.tsx → file
            if ".stories" in stem:
                target_name = stem.split(".stories")[0]
                match_type = "story"
            elif ".story" in stem:
                target_name = stem.split(".story")[0]
                match_type = "story"
            # file.test.tsx → file
            elif ".test" in stem:
                target_name = stem.split(".test")[0]
                match_type = "test"
            elif ".spec" in stem:
                target_name = stem.split(".spec")[0]
                match_type = "spec"

        # Python patterns
        elif lang == "python":
            # test_file.py → file
            if stem.startswith("test_"):
                target_name = stem[5:]  # strip "test_"
                match_type = "prefix-test"
            # file_test.py → file
            elif stem.endswith("_test"):
                target_name = stem[:-5]  # strip "_test"
                match_type = "suffix-test"
            # conftest.py, test fixtures — skip

        if not target_name:
            continue

        # Try to find the matching component.
        # Priority: same dir > sibling dir > same package > global.
        # Critical rule: if we find candidates at a closer scope, stop.
        # Global fallback limited to 1 best match to prevent fan-out
        # (test_agency.py → 7 agency.py files is noise, not signal).
        target_lower = target_name.lower()
        target_kebab = pascal_to_kebab(target_name)
        target_snake = pascal_to_snake(target_name)
        variants = [target_lower, target_kebab, target_snake]

        candidates = set()

        # 1. Same directory (strongest signal)
        local = dir_files.get(parent, {})
        for v in variants:
            if v in local:
                candidates.add(local[v])

        # 2. Sibling directories (components/ next to __tests__/)
        if not candidates:
            parent_of_parent = os.path.dirname(parent)
            if parent_of_parent:
                for sibling_dir, sibling_files in dir_files.items():
                    if sibling_dir.startswith(parent_of_parent) and sibling_dir != parent:
                        for v in variants:
                            if v in sibling_files:
                                candidates.add(sibling_files[v])

        # 3. Same package (for Python monorepo: test/ and schema/ under travel-api/)
        if not candidates:
            test_pkg = None
            # Walk up to find package root
            d = parent
            while d:
                if d in [pkg for pkg in dir_files]:
                    pass
                # Use first path component as rough package
                if "/" in f:
                    test_pkg = f.split("/")[0]
                break

            if test_pkg:
                for v in variants:
                    if v in all_stems:
                        pkg_matches = [c for c in all_stems[v] if c.startswith(test_pkg + "/") and c != f]
                        candidates.update(pkg_matches)

        # 4. Global fallback — only if exactly 1 match (ambiguous = skip)
        if not candidates:
            for v in variants:
                if v in all_stems:
                    global_matches = [c for c in all_stems[v] if c != f]
                    if len(global_matches) == 1:
                        candidates.add(global_matches[0])
                    break  # don't try other variants if first found ambiguous

        for comp in candidates:
            if comp != f:
                edges.append((f, comp, match_type))

    return edges


def analyze_overlap(repo_path, name, edges, files):
    """Check how many naming convention edges overlap with existing import edges."""
    from prototype_clustering_v3 import (
        resolve_python_imports,
        resolve_typescript_imports,
        find_tsconfig_paths,
    )

    py_files = [f for f in files if classify_language(f) == "python"]
    ts_files = [f for f in files if classify_language(f) == "typescript"]

    py_edges = resolve_python_imports(repo_path, py_files)
    tsconfig = find_tsconfig_paths(repo_path, ts_files)
    ts_edges = resolve_typescript_imports(repo_path, ts_files, tsconfig)

    import_pairs = set()
    for s, t in py_edges + ts_edges:
        import_pairs.add(tuple(sorted([s, t])))

    naming_pairs = set()
    for s, t, _ in edges:
        naming_pairs.add(tuple(sorted([s, t])))

    overlap = naming_pairs & import_pairs
    novel = naming_pairs - import_pairs

    print(f"\n  Import overlap analysis:")
    print(f"    Naming convention edges: {len(naming_pairs)}")
    print(f"    Already in import graph: {len(overlap)} ({len(overlap)*100//max(len(naming_pairs),1)}%)")
    print(f"    Novel edges (2b adds):   {len(novel)} ({len(novel)*100//max(len(naming_pairs),1)}%)")

    return novel


def main():
    repos = [
        ("/Users/sanjay.kotagiri/Documents/code/project-travel-prod-bug-fixes", "travel-prod"),
        ("/Users/sanjay.kotagiri/Documents/code/tmp/find-your-tribe", "find-your-tribe"),
        ("/Users/sanjay.kotagiri/Documents/code/tmp/speed", "SPEED"),
    ]

    for repo_path, name in repos:
        if not os.path.exists(repo_path):
            continue

        print(f"\n{'='*60}")
        print(f"  NAMING CONVENTION MATCHING: {name}")
        print(f"{'='*60}")

        files = get_code_files(repo_path)
        edges = find_naming_convention_edges(repo_path, files)

        # Categorize
        by_type = defaultdict(list)
        for src, tgt, mtype in edges:
            by_type[mtype].append((src, tgt))

        print(f"\n  Total files: {len(files)}")
        print(f"  Total naming edges: {len(edges)}")
        print(f"\n  By match type:")
        for mtype, pairs in sorted(by_type.items(), key=lambda x: -len(x[1])):
            print(f"    {mtype}: {len(pairs)}")

        # Show sample matches
        print(f"\n  Sample matches:")
        shown = 0
        for src, tgt, mtype in edges:
            if shown >= 10:
                break
            print(f"    [{mtype}] {os.path.basename(src)}  →  {os.path.basename(tgt)}")
            print(f"           {src}")
            print(f"           {tgt}")
            shown += 1

        # Check unmatched test/story files
        matched_sources = {src for src, _, _ in edges}
        unmatched = []
        for f in files:
            stem = Path(f).stem
            lang = classify_language(f)
            is_test_story = False
            if lang == "typescript":
                is_test_story = any(m in stem for m in [".stories", ".story", ".test", ".spec"])
            elif lang == "python":
                is_test_story = stem.startswith("test_") or stem.endswith("_test")

            if is_test_story and f not in matched_sources:
                unmatched.append(f)

        print(f"\n  Unmatched test/story files: {len(unmatched)}")
        for f in unmatched[:10]:
            print(f"    {f}")
        if len(unmatched) > 10:
            print(f"    ... and {len(unmatched) - 10} more")

        # Check overlap with import edges
        novel = analyze_overlap(repo_path, name, edges, files)

        # Show a few novel edges (ones import analysis misses)
        if novel:
            print(f"\n  Novel edges (not in import graph):")
            shown = 0
            novel_with_type = [(s, t, mt) for s, t, mt in edges if tuple(sorted([s, t])) in novel]
            for src, tgt, mtype in novel_with_type[:8]:
                print(f"    [{mtype}] {os.path.basename(src)}  →  {os.path.basename(tgt)}")
            if len(novel) > 8:
                print(f"    ... and {len(novel) - 8} more")


if __name__ == "__main__":
    main()
