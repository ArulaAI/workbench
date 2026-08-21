#!/usr/bin/env python3
"""Contract verification — technology-agnostic existence checks.

Verifies that the codebase contains the artifacts declared in contract.json.
Checks EXISTENCE only (does the file/symbol exist?). Semantic correctness
(are columns right? are FKs valid?) is the LLM reviewer's job.

Usage:
    python3 contract_verify.py <contract.json> <project_root>

Output: JSON with passed/failed results per entity.
Exit code: 0 if all checks pass, 1 if any fail.
"""

import json
import os
import sys


# ── Entity type inference ─────────────────────────────────────────


def _infer_entity_type(entity):
    """Infer entity type from fields. Backward compat for contracts without 'type'."""
    if "type" in entity:
        return entity["type"]
    # Legacy: table field with path-like value
    table = entity.get("table", "")
    if "/" in table or "." in table:
        if ":" in table:
            return "function"
        return "file"
    return "database"


# ── Entity verification ──────────────────────────────────────────


def verify_file_entity(entity, project_root):
    """Check that a file entity exists on disk.

    Returns list of {check, passed, detail} dicts.
    """
    results = []
    path = entity.get("path") or entity.get("table", "")
    name = entity.get("name", path)

    if not path:
        results.append({
            "check": f"File entity '{name}'",
            "passed": False,
            "detail": "No path declared — cannot verify",
        })
        return results

    # Handle parameterized paths like .speed/defects/<name>/state.json
    if "<" in path and ">" in path:
        parts = path.split("/")
        static_parts = []
        for part in parts:
            if "<" in part:
                break
            static_parts.append(part)
        parent_dir = os.path.join(project_root, *static_parts) if static_parts else project_root
        exists = os.path.isdir(parent_dir)
        results.append({
            "check": f"File entity '{name}'",
            "passed": exists,
            "detail": f"Parameterized path '{path}' — parent dir '{'/'.join(static_parts) or '.'}' {'exists' if exists else 'NOT FOUND'}",
        })
    else:
        full_path = os.path.join(project_root, path)
        exists = os.path.exists(full_path)
        results.append({
            "check": f"File entity '{name}'",
            "passed": exists,
            "detail": f"Path '{path}' {'exists' if exists else 'NOT FOUND'}",
        })

    return results


def verify_function_entity(entity, project_root):
    """Check that a function entity's file exists and contains the symbol.

    Returns list of {check, passed, detail} dicts.
    """
    results = []
    raw = entity.get("path") or entity.get("table", "")
    # Handle legacy "file:func" format in table field
    if ":" in raw and not entity.get("path"):
        path = raw.split(":")[0]
        func_name = raw.split(":")[-1]
    else:
        path = raw
        func_name = entity.get("function", "")

    name = entity.get("name", f"{path}:{func_name}" if func_name else path)

    if not path:
        results.append({
            "check": f"Function entity '{name}'",
            "passed": False,
            "detail": "No path declared — cannot verify",
        })
        return results

    full_path = os.path.join(project_root, path)

    if not os.path.exists(full_path):
        results.append({
            "check": f"Function entity '{name}'",
            "passed": False,
            "detail": f"File '{path}' NOT FOUND",
        })
        return results

    # File exists — check for the symbol name in content
    try:
        content = open(full_path).read()
    except OSError as e:
        results.append({
            "check": f"Function entity '{name}'",
            "passed": False,
            "detail": f"Cannot read '{path}': {e}",
        })
        return results

    if func_name and func_name in content:
        results.append({
            "check": f"Function entity '{name}'",
            "passed": True,
            "detail": f"File '{path}' exists and contains '{func_name}'",
        })
    elif func_name:
        results.append({
            "check": f"Function entity '{name}'",
            "passed": False,
            "detail": f"File '{path}' exists but '{func_name}' NOT FOUND in content",
        })
    else:
        results.append({
            "check": f"Function entity '{name}'",
            "passed": True,
            "detail": f"File '{path}' exists (no function name specified)",
        })

    return results


def verify_database_entity(entity, project_root):
    """Check that a database entity's model file exists and contains the model class.

    If the entity has a `path`, checks file existence (and `function` as symbol).
    If no `path`, emits an advisory — the entity is not verifiable by this script.

    Returns list of {check, passed, detail} dicts.
    """
    path = entity.get("path", "")
    name = entity.get("name", entity.get("table", "unknown"))

    if path:
        # Has a path — verify like a function entity (file + optional symbol)
        return verify_function_entity(entity, project_root)

    # No path — legacy contract with only a table name
    table = entity.get("table", "")
    return [{
        "check": f"Database entity '{name}'",
        "passed": True,
        "detail": f"Table '{table}' declared without path — existence not verifiable by automated check (LLM agents will verify)",
    }]


# ── Verification ──────────────────────────────────────────────────


def verify_contract(contract, project_root, csg=None):
    """Verify contract entities exist in the project.

    Checks existence only. Semantic correctness (key_fields, relationships)
    is verified by LLM agents (reviewer, coherence checker).

    When CSG is available, uses symbol-layer verification for richer checks
    (verifies key_fields as actual attributes, not just file/class grep).

    Args:
        contract: contract.json dict
        project_root: path to project root
        csg: semantic-graph.json dict (optional, for enhanced verification)

    Returns list of {check, passed, detail} dicts.
    """
    results = []

    entities = contract.get("entities", [])

    # Empty entities = failure — every feature creates something
    if not entities:
        results.append({
            "check": "Entity coverage",
            "passed": False,
            "detail": "No entities declared — every feature must declare verifiable artifacts",
        })
        return results

    # Build CSG lookup indices for enhanced verification
    csg_by_name = {}
    csg_by_file = {}
    if csg:
        for node in csg.get("nodes", []):
            name = node.get("name", "")
            if name:
                csg_by_name.setdefault(name, []).append(node)
            file_path = node.get("file", "")
            if file_path:
                csg_by_file.setdefault(file_path, []).append(node)

    for entity in entities:
        entity_type = _infer_entity_type(entity)

        if entity_type == "file":
            results.extend(verify_file_entity(entity, project_root))
        elif entity_type == "function":
            results.extend(verify_function_entity(entity, project_root))
            # Enhanced: CSG symbol check
            if csg:
                results.extend(_verify_with_csg(entity, csg_by_name))
        elif entity_type == "database":
            results.extend(verify_database_entity(entity, project_root))
            # Enhanced: CSG schema check
            if csg:
                results.extend(_verify_schema_with_csg(entity, csg_by_name))
        else:
            results.append({
                "check": f"Entity '{entity.get('name', '?')}'",
                "passed": False,
                "detail": f"Unknown entity type '{entity_type}'",
            })

    return results


def _verify_with_csg(entity, csg_by_name):
    """Enhanced function entity verification using CSG symbol lookup."""
    results = []
    func_name = entity.get("function", "")
    name = entity.get("name", func_name)

    if not func_name:
        return results

    matches = csg_by_name.get(func_name, [])
    if matches:
        node = matches[0]
        results.append({
            "check": f"CSG symbol '{name}'",
            "passed": True,
            "detail": f"Symbol '{func_name}' found in CSG: {node.get('kind', '?')} at {node.get('file', '?')}:{node.get('line', '?')}",
        })
    else:
        results.append({
            "check": f"CSG symbol '{name}'",
            "passed": False,
            "detail": f"Symbol '{func_name}' not found in CSG — may be missing or renamed",
        })

    return results


def _verify_schema_with_csg(entity, csg_by_name):
    """Enhanced database entity verification using CSG schema annotations."""
    results = []
    name = entity.get("name", entity.get("table", "?"))
    key_fields = entity.get("key_fields", [])

    if not key_fields:
        return results

    # Find model class in CSG
    matches = csg_by_name.get(name, [])
    class_nodes = [m for m in matches if m.get("kind") == "class"]

    if not class_nodes:
        return results

    node = class_nodes[0]
    schema = node.get("schema")

    if not schema:
        # Class exists but no schema annotation detected
        results.append({
            "check": f"CSG schema for '{name}'",
            "passed": True,
            "detail": f"Class '{name}' found in CSG but no ORM schema detected (grep verification still applies)",
        })
        return results

    # Verify key_fields as actual columns
    columns = {c.get("name", "") for c in schema.get("columns", [])}
    for field in key_fields:
        if field in columns:
            results.append({
                "check": f"CSG column '{name}.{field}'",
                "passed": True,
                "detail": f"Column '{field}' confirmed in CSG schema for '{name}'",
            })
        else:
            results.append({
                "check": f"CSG column '{name}.{field}'",
                "passed": False,
                "detail": f"Column '{field}' NOT found in CSG schema for '{name}'. Known columns: {', '.join(sorted(columns)[:10])}",
            })

    return results


# ── Main ──────────────────────────────────────────────────────────


def main():
    if len(sys.argv) < 3:
        print(json.dumps({"error": f"Usage: {sys.argv[0]} <contract.json> <project_root> [csg.json]"}))
        sys.exit(2)

    contract_path = sys.argv[1]
    project_root = sys.argv[2]
    csg_path = sys.argv[3] if len(sys.argv) > 3 else None

    try:
        with open(contract_path) as f:
            contract = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(json.dumps({"error": f"Failed to read contract: {str(e)}"}))
        sys.exit(2)

    # Load CSG if available (enhanced verification)
    csg = None
    if csg_path:
        try:
            with open(csg_path) as f:
                csg = json.load(f)
        except (OSError, json.JSONDecodeError):
            pass  # Graceful degradation — run without CSG
    else:
        # Try default location
        default_csg = os.path.join(project_root, ".speed", "context", "semantic-graph.json")
        try:
            with open(default_csg) as f:
                csg = json.load(f)
        except (OSError, json.JSONDecodeError):
            pass

    results = verify_contract(contract, project_root, csg=csg)

    passed = all(r["passed"] for r in results)

    output = {
        "passed": passed,
        "results": results,
    }

    print(json.dumps(output))
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
