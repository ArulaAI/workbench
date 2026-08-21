#!/usr/bin/env python3
"""End-to-end test: Layer 1 build on the SPEED codebase itself."""

import json
import os
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from lib.context.layer1 import build_layer1

CONTEXT_DIR = os.path.join(PROJECT_ROOT, ".speed", "context")
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


# ── Test 1: Fresh build ──────────────────────────────────────
print("\n=== Test 1: Fresh Layer 1 Build ===")

# Clean slate
if os.path.exists(CONTEXT_DIR):
    import shutil
    shutil.rmtree(CONTEXT_DIR)

t0 = time.time()
result = build_layer1(PROJECT_ROOT, fresh=True)
elapsed = time.time() - t0

print(f"  Build time: {elapsed:.3f}s")
print(f"  Status: {result.get('status')}")

# Check status
check("build returns 'built'", result["status"] == "built")

# Check timing exists
check("timing.total present", "total" in result.get("timing", {}))
check("build under 10s", elapsed < 10.0, f"took {elapsed:.1f}s")

# Check project map artifact
pm_path = os.path.join(CONTEXT_DIR, "project-map.json")
check("project-map.json exists", os.path.exists(pm_path))
if os.path.exists(pm_path):
    with open(pm_path) as f:
        pm = json.load(f)
    check("project map has files", len(pm.get("files", [])) > 0,
          f"got {len(pm.get('files', []))} files")
    check("project map has summary", "summary" in pm)
    file_count = pm["summary"].get("total_files", 0)
    check("project map has >50 files", file_count > 50,
          f"got {file_count}")
    print(f"  Project map: {file_count} files")

# Check CSG artifact
csg_path = os.path.join(CONTEXT_DIR, "semantic-graph.json")
check("semantic-graph.json exists", os.path.exists(csg_path))
if os.path.exists(csg_path):
    with open(csg_path) as f:
        csg = json.load(f)
    node_count = len(csg.get("nodes", []))
    edge_count = len(csg.get("edges", []))
    cluster_count = len(csg.get("clusters", []))
    check("CSG has nodes", node_count > 0, f"got {node_count}")
    check("CSG has edges", edge_count > 0, f"got {edge_count}")
    check("CSG has clusters", cluster_count > 0, f"got {cluster_count}")
    print(f"  CSG: {node_count} nodes, {edge_count} edges, {cluster_count} clusters")

    # Verify CSG node structure
    if csg["nodes"]:
        node = csg["nodes"][0]
        check("CSG node has 'name'", "name" in node)
        check("CSG node has 'kind'", "kind" in node)
        check("CSG node has 'file'", "file" in node)

    # Verify impact is embedded per-node
    nodes_with_impact = [n for n in csg["nodes"] if n.get("impact")]
    check("CSG nodes have impact data", len(nodes_with_impact) > 0,
          f"{len(nodes_with_impact)}/{node_count} nodes have impact")
    if nodes_with_impact:
        imp = nodes_with_impact[0]["impact"]
        check("impact has 'blast_radius'", "blast_radius" in imp)
        check("impact has 'stability'", "stability" in imp)
        check("impact has 'centrality'", "centrality" in imp)

    # Verify cluster_edges exist
    check("CSG has cluster_edges", "cluster_edges" in csg)

# Check skeletons directory
skel_dir = os.path.join(CONTEXT_DIR, "skeletons")
check("skeletons/ dir exists", os.path.isdir(skel_dir))
if os.path.isdir(skel_dir):
    # Count skeleton files recursively
    skel_count = 0
    for root, dirs, files in os.walk(skel_dir):
        skel_count += sum(1 for f in files if f.endswith(".skeleton"))
    check("skeletons produced", skel_count > 0, f"got {skel_count}")
    print(f"  Skeletons: {skel_count} files")

# Check .githead marker
githead_path = os.path.join(CONTEXT_DIR, ".githead")
check(".githead marker written", os.path.exists(githead_path))

# Check build summary
summary_path = os.path.join(CONTEXT_DIR, "build-summary.json")
check("build-summary.json exists", os.path.exists(summary_path))
if os.path.exists(summary_path):
    with open(summary_path) as f:
        summary = json.load(f)
    check("summary has timing", "timing" in summary)
    check("summary has artifacts", "artifacts" in summary)

# Check result dict structure
check("result has extraction_stats", "extraction_stats" in result)
check("result has csg_stats", "csg_stats" in result)
check("result has skeleton_stats", "skeleton_stats" in result)
check("result has project_map_summary", "project_map_summary" in result)


# ── Test 2: Staleness check (should skip) ────────────────────
print("\n=== Test 2: Staleness Check (should skip) ===")

t0 = time.time()
result2 = build_layer1(PROJECT_ROOT, fresh=False)
skip_time = time.time() - t0

check("second build returns 'skipped'", result2["status"] == "skipped")
check("skip is fast (<0.1s)", skip_time < 0.1, f"took {skip_time:.3f}s")
print(f"  Skip time: {skip_time:.3f}s")


# ── Test 3: fresh=True forces rebuild ────────────────────────
print("\n=== Test 3: fresh=True Forces Rebuild ===")

t0 = time.time()
result3 = build_layer1(PROJECT_ROOT, fresh=True)
rebuild_time = time.time() - t0

check("fresh rebuild returns 'built'", result3["status"] == "built")
check("rebuild produced artifacts", len(result3.get("artifacts", {})) > 0)
print(f"  Rebuild time: {rebuild_time:.3f}s")


# ── Test 4: Spec alignment (with real SPEED specs) ───────────
print("\n=== Test 4: Spec Alignment (speed-security) ===")

# Use actual SPEED specs — the same ones the related spec compression design targets
tech_spec_path = os.path.join(PROJECT_ROOT, "specs", "tech", "speed-security.md")
product_spec_path = os.path.join(PROJECT_ROOT, "specs", "product", "speed-security.md")

spec_files = {}
for label, path in [("tech", tech_spec_path), ("product", product_spec_path)]:
    if os.path.exists(path):
        with open(path) as f:
            spec_files[path] = f.read()
        print(f"  Loaded {label} spec: {os.path.relpath(path, PROJECT_ROOT)}")
    else:
        print(f"  SKIP: {label} spec not found at {path}")

if spec_files:
    result4 = build_layer1(
        PROJECT_ROOT,
        spec_files=spec_files,
        fresh=True,
    )

    check("spec alignment produced", "spec_alignment" in result4.get("artifacts", {}))

    # Load and inspect the actual claims
    align_path = os.path.join(CONTEXT_DIR, "spec-alignment.json")
    if os.path.exists(align_path):
        with open(align_path) as f:
            alignment = json.load(f)

        claims = alignment.get("claims", [])
        summary = alignment.get("summary", {})
        claim_count = summary.get("total_claims", 0)
        confirmed = summary.get("confirmed", 0)
        missing = summary.get("missing", 0)
        divergent = summary.get("divergent", 0)

        check("spec claims >= 25", claim_count >= 25,
              f"got {claim_count} (backtick extraction produces ~57 claims)")
        print(f"  Claims: {claim_count} total — {confirmed} confirmed, {missing} missing, {divergent} divergent")

        # Group claims by type and print each
        by_type: dict[str, list] = {}
        for c in claims:
            ct = c.get("claim_type", "unknown")
            by_type.setdefault(ct, []).append(c)

        print(f"\n  Claims by type:")
        for ctype, type_claims in sorted(by_type.items()):
            print(f"    {ctype} ({len(type_claims)}):")
            for c in type_claims:
                status_marker = {"confirmed": "+", "missing": "-", "divergent": "~"}.get(c["status"], "?")
                print(f"      [{status_marker}] {c['entity']}")

        # Claim type distribution checks
        file_exists = [c for c in claims if c["claim_type"] == "file_exists"]
        entity_defined = [c for c in claims if c["claim_type"] == "entity_defined"]
        function_exists = [c for c in claims if c["claim_type"] == "function_exists"]

        check("file_exists >= 10", len(file_exists) >= 10,
              f"got {len(file_exists)}")
        check("function_exists >= 3", len(function_exists) >= 3,
              f"got {len(function_exists)}")
        check("entity_defined >= 5", len(entity_defined) >= 5,
              f"got {len(entity_defined)}")

        # Quality check: no garbage entities from the old regex extraction
        garbage = {"after", "doesn", "definition", "to", "directly",
                   "Ecosystem", "Decision", "File", "ID", "Risk"}
        extracted_entities = {c["entity"] for c in claims}
        check("no garbage entities", len(garbage & extracted_entities) == 0,
              f"found garbage: {garbage & extracted_entities}")

        print(f"\n  Entities relevant for related spec scoring:")
        print(f"    entity_defined:  {len(entity_defined)}")
        print(f"    file_exists:     {len(file_exists)}")
        print(f"    function_exists: {len(function_exists)}")

        scoring_entities = set()
        for c in entity_defined + function_exists:
            scoring_entities.add(c["entity"])
        print(f"    unique scoring entities: {len(scoring_entities)}")
        check("scoring entities >= 15", len(scoring_entities) >= 15,
              f"got {len(scoring_entities)} (quality gate for related spec compression)")
else:
    print("  SKIP: no spec files found")


# ── Summary ──────────────────────────────────────────────────
print(f"\n{'='*50}")
print(f"Layer 1 E2E Results: {passed} passed, {failed} failed")
if failed == 0:
    print("ALL TESTS PASSED")
else:
    print(f"FAILURES: {failed}")
    sys.exit(1)
