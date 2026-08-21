"""Spec Context — Layer 2, Dimension 3.

Pulls spec sections relevant to a task via spec_references (explicit
pointers from the Architect) + heuristic fallback (heading/entity matching).
Filters spec-alignment claims to this task's symbols.

Usage:
    from lib.context.spec_context import build_spec_context
    ctx = build_spec_context(task, spec_files, spec_alignment, csg)

Tech spec: tech-spec-context-constructor.md → Layer 2 § Spec Context
"""

from __future__ import annotations

import os
import re
from typing import Any

from .utils import write_json, read_json


def build_spec_context(
    task: dict,
    spec_files: dict[str, str],
    spec_alignment: dict | None = None,
    csg: dict | None = None,
) -> dict:
    """Build spec context for a task.

    Args:
        task: task dict (with spec_references, files_touched, description)
        spec_files: {spec_file_path: content}
        spec_alignment: spec-alignment.json dict (from Layer 1)
        csg: semantic-graph.json dict (for entity matching)

    Returns:
        spec-context.json dict.
    """
    # 1. Primary path: Architect-declared spec_references
    relevant_sections = _pull_spec_references(task, spec_files)

    # 2. Fallback path: heuristic matching for uncovered sections
    if not relevant_sections:
        relevant_sections = _heuristic_match(task, spec_files)

    # 3. Filter alignment claims to this task's symbols
    alignment_status = _filter_alignment(task, spec_alignment, csg)

    # 4. Extract contract excerpt
    contract_excerpt = _extract_contract_excerpt(task, csg)

    return {
        "relevant_spec_sections": relevant_sections,
        "alignment_status": alignment_status,
        "contract_excerpt": contract_excerpt,
    }


def _pull_spec_references(
    task: dict,
    spec_files: dict[str, str],
) -> list[dict]:
    """Pull spec sections via explicit spec_references from the Architect."""
    refs = task.get("spec_references", [])
    if not refs:
        return []

    sections = []
    for ref in refs:
        spec_name = ref.get("spec", "")
        section_name = ref.get("section", "")
        requirement = ref.get("requirement", "")

        # Find matching spec file
        content = _find_spec_content(spec_name, spec_files)
        if not content:
            sections.append({
                "source": {"spec": spec_name, "section": section_name},
                "content": f"[Spec '{spec_name}' not found]",
                "requirement": requirement,
            })
            continue

        # Extract section from spec content
        section_text = _extract_section(content, section_name)
        sections.append({
            "source": {"spec": spec_name, "section": section_name},
            "content": section_text or f"[Section '{section_name}' not found in {spec_name}]",
            "requirement": requirement,
        })

    return sections


def _heuristic_match(
    task: dict,
    spec_files: dict[str, str],
) -> list[dict]:
    """Heuristic fallback: match task description → spec sections."""
    description = task.get("description", "") + " " + task.get("title", "")

    # Extract entity names from description
    entities = set(re.findall(r'[A-Z][a-zA-Z]+', description))
    # Filter common words
    entities -= {"The", "This", "That", "Each", "Every", "Some", "Any", "All",
                 "When", "Where", "How", "What", "Create", "Build", "Add",
                 "Update", "Delete", "Remove", "With", "From", "Into"}

    sections = []
    for spec_path, content in spec_files.items():
        lines = content.splitlines()
        current_section = ""
        section_start = 0
        section_lines: list[str] = []

        for i, line in enumerate(lines):
            heading = re.match(r"^(#{1,4})\s+(.+)", line)
            if heading:
                # Check previous section for entity matches
                if current_section and section_lines:
                    section_text = "\n".join(section_lines)
                    if _section_matches(section_text, entities):
                        sections.append({
                            "source": {"file": spec_path, "section": current_section},
                            "content": section_text,
                        })

                current_section = heading.group(2).strip()
                section_start = i
                section_lines = [line]
            elif current_section:
                section_lines.append(line)

        # Check last section
        if current_section and section_lines:
            section_text = "\n".join(section_lines)
            if _section_matches(section_text, entities):
                sections.append({
                    "source": {"file": spec_path, "section": current_section},
                    "content": section_text,
                })

    return sections[:10]  # Limit to 10 sections


def _section_matches(section_text: str, entities: set[str]) -> bool:
    """Check if a spec section mentions any of the entities."""
    for entity in entities:
        if entity.lower() in section_text.lower():
            return True
    return False


def _filter_alignment(
    task: dict,
    spec_alignment: dict | None,
    csg: dict | None,
) -> list[dict]:
    """Filter spec-alignment claims relevant to this task's symbols."""
    if not spec_alignment:
        return []

    files_touched = set(task.get("files_touched", []))

    # Get entities in files_touched from CSG
    task_entities: set[str] = set()
    if csg:
        for node in csg.get("nodes", []):
            if node["file"] in files_touched:
                task_entities.add(node["name"])

    relevant = []
    for claim in spec_alignment.get("claims", []):
        entity = claim.get("entity", "")
        # Include if: entity is in task's files, or entity name matches task symbols
        if entity in task_entities or _entity_in_files(entity, files_touched):
            relevant.append({
                "claim": claim.get("claim_text", ""),
                "status": claim.get("status", ""),
                "evidence": claim.get("evidence", ""),
            })

    return relevant


def _entity_in_files(entity: str, files: set[str]) -> bool:
    """Check if an entity name appears in any of the file paths."""
    entity_lower = entity.lower()
    for f in files:
        if entity_lower in f.lower():
            return True
    return False


def _extract_contract_excerpt(task: dict, csg: dict | None) -> dict:
    """Extract contract-relevant info for entities this task creates."""
    files_touched = task.get("files_touched", [])

    entities_created = []
    relationships_established = []

    if csg:
        for node in csg.get("nodes", []):
            if node["file"] in files_touched and node["kind"] == "class":
                entity_info = {"name": node["name"], "file": node["file"]}
                schema = node.get("schema")
                if schema:
                    entity_info["table"] = schema.get("table_name")
                    entity_info["columns"] = [c["name"] for c in schema.get("columns", [])]
                    for rel in schema.get("relationships", []):
                        relationships_established.append({
                            "from": node["name"],
                            "to": rel.get("target_model", ""),
                            "type": rel.get("relationship_type", ""),
                        })
                entities_created.append(entity_info)

    return {
        "entities_this_task_creates": entities_created,
        "relationships_this_task_establishes": relationships_established,
    }


def _find_spec_content(spec_name: str, spec_files: dict[str, str]) -> str | None:
    """Find spec content by name (partial match on filename)."""
    for path, content in spec_files.items():
        basename = os.path.basename(path).lower()
        if spec_name.lower() in basename or basename.startswith(spec_name.lower()):
            return content
    return None


def _extract_section(content: str, section_name: str) -> str | None:
    """Extract a section from markdown content by heading match."""
    lines = content.splitlines()
    in_section = False
    section_lines = []
    section_level = 0

    for line in lines:
        heading = re.match(r"^(#{1,6})\s+(.+)", line)
        if heading:
            level = len(heading.group(1))
            title = heading.group(2).strip()

            if title.lower() == section_name.lower():
                in_section = True
                section_level = level
                section_lines.append(line)
                continue
            elif in_section and level <= section_level:
                break

        if in_section:
            section_lines.append(line)

    return "\n".join(section_lines) if section_lines else None


# ── Persistence ──────────────────────────────────────────────


def save_spec_context(spec_context: dict, task_context_dir: str) -> str:
    path = os.path.join(task_context_dir, "spec-context.json")
    write_json(path, spec_context)
    return path


def load_spec_context(task_context_dir: str) -> dict:
    path = os.path.join(task_context_dir, "spec-context.json")
    return read_json(path)
