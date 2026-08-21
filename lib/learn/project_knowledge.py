"""Project Knowledge pipeline: seed, gap detection, and staleness checking.

Three public functions build and maintain project-knowledge-drafts.json:
- seed_knowledge: scans project files for explicit knowledge markers
- detect_knowledge_gaps: finds areas with repeated failures and no documentation
- check_staleness: flags entries in project-knowledge.json that may be outdated
"""

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from lib.learn.conventions import _atomic_write


# ── Dataclass ──────────────────────────────────────────────────────────────


@dataclass
class DraftEntry:
    """Draft entry for project-knowledge-drafts.json."""

    id: str                    # "pk-draft-<16-char hash>"
    knowledge: str             # the knowledge snippet or question
    why_it_matters: str        # rationale for including this entry
    applies_to: list[str]      # file paths or glob patterns
    agents: list[str]          # which agents should receive this
    tags: list[str]            # categorization tags
    source: str                # 'seeded', 'system-prompted', or 'stale-flag'
    draft_reason: str          # provenance: source file, line, or mechanism
    staleness_flag: str        # description of staleness issue, or ""
    last_verified: str | None  # ISO 8601 date, or None


# ── Private helpers ────────────────────────────────────────────────────────


def _draft_id(content: str) -> str:
    """Generate a stable pk-draft- ID from a content string."""
    digest = hashlib.sha256(content.encode()).hexdigest()[:16]
    return f"pk-draft-{digest}"


# Denylist for sensitive files that must never be read
_DENYLIST_NAMES = {".env", ".env.local"}
_DENYLIST_SUFFIXES = {".key", ".pem"}
_DENYLIST_PREFIXES = {"credentials."}

# Keywords that indicate noteworthy inline comments
_KNOWLEDGE_KEYWORDS = re.compile(
    r"\b(IMPORTANT|NOTE|HACK|ASSUMPTION|DO\s+NOT|NEVER|ALWAYS)\b",
    re.IGNORECASE,
)

# Inline comment pattern for Python, JS/TS, and Bash
_COMMENT_LINE = re.compile(r"^\s*(#|//)\s*(.*)")

# Version pattern for staleness version checking
_VERSION_PATTERN = re.compile(r"\b\d+\.\d+(?:\.\d+)?\b")

# Lock/manifest files that record dependency versions
_LOCK_FILES = ["requirements.txt", "package.json", "Cargo.toml", "go.sum"]

# Observation types that indicate repeated failures
_FAILURE_TYPES = frozenset({"retry", "gate_failure", "guardian_verdict"})

# Directories to skip when scanning source files
_SKIP_DIRS = frozenset({
    "node_modules", ".venv", "venv", "__pycache__", ".git", ".mypy_cache",
    ".pytest_cache", "dist", "build", ".speed",
})

_STALENESS_DAYS = 90
_GAP_THRESHOLD = 3


def _is_denylisted(path: Path) -> bool:
    """Return True if the path matches the sensitive-file denylist."""
    name = path.name
    if name in _DENYLIST_NAMES:
        return True
    for suffix in _DENYLIST_SUFFIXES:
        if name.endswith(suffix):
            return True
    for prefix in _DENYLIST_PREFIXES:
        if name.startswith(prefix):
            return True
    return False


def _in_skip_dir(path: Path) -> bool:
    """Return True if any component of path is in the skip list."""
    return bool(_SKIP_DIRS.intersection(path.parts))


def _entry_to_dict(entry: DraftEntry) -> dict:
    return {
        "id": entry.id,
        "knowledge": entry.knowledge,
        "why_it_matters": entry.why_it_matters,
        "applies_to": entry.applies_to,
        "agents": entry.agents,
        "tags": entry.tags,
        "source": entry.source,
        "draft_reason": entry.draft_reason,
        "staleness_flag": entry.staleness_flag,
        "last_verified": entry.last_verified,
    }


def _load_drafts(drafts_path: Path) -> dict[str, dict]:
    """Load existing drafts from disk, indexed by ID. Empty dict on failure."""
    if not drafts_path.exists():
        return {}
    try:
        data = json.loads(drafts_path.read_text())
        if isinstance(data, list):
            return {e["id"]: e for e in data if isinstance(e, dict) and "id" in e}
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _merge_and_write(drafts_path: Path, new_entries: list[DraftEntry]) -> None:
    """Merge new entries with existing drafts (skip duplicate IDs) and write atomically."""
    existing = _load_drafts(drafts_path)
    for entry in new_entries:
        if entry.id not in existing:
            existing[entry.id] = _entry_to_dict(entry)
    _atomic_write(drafts_path, list(existing.values()))


# ── seed_knowledge ─────────────────────────────────────────────────────────


def seed_knowledge(project_root: Path, memory_dir: Path) -> list[DraftEntry]:
    """Scan project files and generate draft knowledge entries.

    Covers documentation files, .env.example, and source code inline comments
    that contain knowledge markers (IMPORTANT, NOTE, HACK, etc.).

    Writes merged results to memory_dir/project-knowledge-drafts.json.
    Never touches project-knowledge.json.
    """
    memory_dir.mkdir(parents=True, exist_ok=True)
    entries: list[DraftEntry] = []

    # ── Documentation files ──────────────────────────────────────────────

    doc_targets: list[Path] = [
        project_root / "README.md",
        project_root / (os.environ.get("SPEED_AGENT_FILE") or "CLAUDE.md"),
        project_root / "CONTRIBUTING.md",
    ]
    for adr_dir in [project_root / "docs" / "adr", project_root / "adr"]:
        if adr_dir.is_dir():
            doc_targets.extend(adr_dir.glob("*.md"))

    for doc_file in doc_targets:
        if not doc_file.is_file():
            continue
        try:
            text = doc_file.read_text(errors="replace")
        except OSError:
            continue
        rel = str(doc_file.relative_to(project_root))
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if not stripped or not _KNOWLEDGE_KEYWORDS.search(stripped):
                continue
            entry_id = _draft_id(f"doc:{rel}:{lineno}:{stripped}")
            entries.append(DraftEntry(
                id=entry_id,
                knowledge=stripped,
                why_it_matters="Explicitly marked as important in project documentation",
                applies_to=[rel],
                agents=["developer", "reviewer", "architect"],
                tags=["documentation", "seeded"],
                source="seeded",
                draft_reason=f"Found in {rel}:{lineno}",
                staleness_flag="",
                last_verified=None,
            ))

    # ── .env.example ─────────────────────────────────────────────────────

    env_example = project_root / ".env.example"
    if env_example.is_file() and not _is_denylisted(env_example):
        try:
            text = env_example.read_text(errors="replace")
        except OSError:
            text = ""

        var_names: list[str] = []
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                # Comment line — check for keywords
                if _KNOWLEDGE_KEYWORDS.search(stripped):
                    entry_id = _draft_id(f"env-comment:{lineno}:{stripped}")
                    entries.append(DraftEntry(
                        id=entry_id,
                        knowledge=stripped,
                        why_it_matters="Environment configuration note in .env.example",
                        applies_to=[".env.example"],
                        agents=["developer"],
                        tags=["environment", "configuration", "seeded"],
                        source="seeded",
                        draft_reason=f"Comment in .env.example:{lineno}",
                        staleness_flag="",
                        last_verified=None,
                    ))
            elif "=" in stripped:
                # Variable name — record it, never record the value
                var_name = stripped.split("=", 1)[0].strip()
                if var_name:
                    var_names.append(var_name)

        if var_names:
            var_list = ", ".join(var_names)
            entry_id = _draft_id(f"env-vars:{var_list}")
            entries.append(DraftEntry(
                id=entry_id,
                knowledge=f"Required environment variables: {var_list}",
                why_it_matters="These variables must be configured for the application to run",
                applies_to=[".env.example"],
                agents=["developer"],
                tags=["environment", "configuration", "seeded"],
                source="seeded",
                draft_reason="Variable names extracted from .env.example",
                staleness_flag="",
                last_verified=None,
            ))

    # ── Source file inline comments ────────────────────────────────────────

    seen: set[Path] = set()
    for pattern in ["**/*.py", "**/*.js", "**/*.ts", "**/*.sh"]:
        for src_file in project_root.glob(pattern):
            if src_file in seen or _is_denylisted(src_file) or _in_skip_dir(src_file):
                continue
            seen.add(src_file)
            try:
                text = src_file.read_text(errors="replace")
            except OSError:
                continue
            rel = str(src_file.relative_to(project_root))
            for lineno, line in enumerate(text.splitlines(), 1):
                m = _COMMENT_LINE.match(line)
                if not m:
                    continue
                comment_text = m.group(2).strip()
                if not comment_text or not _KNOWLEDGE_KEYWORDS.search(comment_text):
                    continue
                entry_id = _draft_id(f"src:{rel}:{lineno}:{comment_text}")
                entries.append(DraftEntry(
                    id=entry_id,
                    knowledge=comment_text,
                    why_it_matters="Flagged in source code as requiring agent awareness",
                    applies_to=[rel],
                    agents=["developer"],
                    tags=["inline-comment", "seeded"],
                    source="seeded",
                    draft_reason=f"Inline comment at {rel}:{lineno}",
                    staleness_flag="",
                    last_verified=None,
                ))

    drafts_path = memory_dir / "project-knowledge-drafts.json"
    _merge_and_write(drafts_path, entries)
    return entries


# ── detect_knowledge_gaps ──────────────────────────────────────────────────


def detect_knowledge_gaps(memory_dir: Path) -> list[DraftEntry]:
    """Detect files with repeated failures and no covering project knowledge.

    Reads observations/*.jsonl, groups retries/failures by file path, and
    generates draft question entries where 3+ failures cluster with no existing
    project-knowledge or conventions coverage.

    Writes merged results to memory_dir/project-knowledge-drafts.json.
    """
    obs_dir = memory_dir / "observations"
    if not obs_dir.is_dir():
        return []

    # Collect file paths already covered by project-knowledge.json
    knowledge_path = memory_dir / "project-knowledge.json"
    covered_paths: set[str] = set()
    if knowledge_path.is_file():
        try:
            data = json.loads(knowledge_path.read_text())
            if isinstance(data, list):
                entries_list = data
            elif isinstance(data, dict):
                entries_list = data.get("entries", [])
            else:
                entries_list = []
            for entry in entries_list:
                if isinstance(entry, dict):
                    for p in entry.get("applies_to", []):
                        covered_paths.add(p)
        except (json.JSONDecodeError, OSError):
            pass

    # Collect file paths covered by conventions.json
    conventions_path = memory_dir / "conventions.json"
    if conventions_path.is_file():
        try:
            conv_data = json.loads(conventions_path.read_text())
            if isinstance(conv_data, list):
                for entry in conv_data:
                    if isinstance(entry, dict):
                        for p in entry.get("scope", []):
                            covered_paths.add(p)
        except (json.JSONDecodeError, OSError):
            pass

    # Group failure observations by file path
    file_failures: dict[str, list[dict]] = {}

    for jsonl_file in sorted(obs_dir.glob("*.jsonl")):
        try:
            text = jsonl_file.read_text(errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obs = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obs, dict):
                continue
            if obs.get("observation_type") not in _FAILURE_TYPES:
                continue
            detail = obs.get("detail", {}) or {}
            file_refs: list[str] = []
            if isinstance(detail.get("files_involved"), list):
                file_refs.extend(f for f in detail["files_involved"] if f)
            elif isinstance(detail.get("file"), str) and detail["file"]:
                file_refs.append(detail["file"])
            elif isinstance(obs.get("applies_to"), list):
                file_refs.extend(f for f in obs["applies_to"] if f)
            for file_ref in file_refs:
                file_failures.setdefault(file_ref, []).append(obs)

    drafts_path = memory_dir / "project-knowledge-drafts.json"
    existing_drafts = _load_drafts(drafts_path)
    entries: list[DraftEntry] = []

    for file_path, failures in file_failures.items():
        if len(failures) < _GAP_THRESHOLD:
            continue
        if file_path in covered_paths:
            continue
        entry_id = _draft_id(f"gap:{file_path}")
        if entry_id in existing_drafts:
            continue
        entries.append(DraftEntry(
            id=entry_id,
            knowledge=f"What should agents know before modifying {file_path}?",
            why_it_matters=(
                f"{len(failures)} retry/failure observations cluster around this file, "
                "suggesting undocumented constraints or patterns"
            ),
            applies_to=[file_path],
            agents=["developer", "architect"],
            tags=["gap", "system-prompted"],
            source="system-prompted",
            draft_reason=f"{len(failures)} failure observations on {file_path}",
            staleness_flag="",
            last_verified=None,
        ))

    if entries:
        _merge_and_write(drafts_path, entries)

    return entries


# ── check_staleness ────────────────────────────────────────────────────────


def _days_since(iso_date: str) -> int | None:
    """Return calendar days elapsed since iso_date, or None if unparseable."""
    try:
        if "T" in iso_date:
            dt = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(iso_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).days
    except (ValueError, TypeError):
        return None


def _collect_lock_versions(project_root: Path) -> set[str]:
    """Extract all version strings from known lock/manifest files."""
    versions: set[str] = set()
    for filename in _LOCK_FILES:
        lock_path = project_root / filename
        if lock_path.is_file():
            try:
                versions |= set(_VERSION_PATTERN.findall(lock_path.read_text(errors="replace")))
            except OSError:
                pass
    return versions


def check_staleness(project_root: Path, memory_dir: Path) -> list[DraftEntry]:
    """Flag entries in project-knowledge.json that appear to be outdated.

    Checks three signals per entry:
    1. applies_to paths no longer exist on disk
    2. Version numbers in the knowledge text are absent from lock files
    3. last_verified is older than 90 days

    Returns empty list if project-knowledge.json is missing.
    Raises json.JSONDecodeError if the file exists but is malformed.

    Writes merged results to memory_dir/project-knowledge-drafts.json.
    """
    knowledge_path = memory_dir / "project-knowledge.json"
    if not knowledge_path.is_file():
        return []

    data = json.loads(knowledge_path.read_text())  # propagate JSONDecodeError
    if not isinstance(data, list):
        return []

    lock_versions = _collect_lock_versions(project_root)
    drafts_path = memory_dir / "project-knowledge-drafts.json"
    entries: list[DraftEntry] = []

    for raw in data:
        if not isinstance(raw, dict):
            continue
        entry_id_base = raw.get("id", "")
        knowledge_text = raw.get("knowledge", "")
        applies_to: list[str] = raw.get("applies_to", [])
        last_verified = raw.get("last_verified")
        reasons: list[str] = []

        # (1) Check applies_to paths exist
        missing = [p for p in applies_to if not (project_root / p).exists()]
        if missing:
            reasons.append(f"applies_to paths no longer exist: {', '.join(missing)}")

        # (2) Check version references against lock files (only when lock files present)
        if lock_versions and knowledge_text:
            text_versions = set(_VERSION_PATTERN.findall(knowledge_text))
            unknown = text_versions - lock_versions
            if unknown:
                reasons.append(
                    f"version references not found in lock files: {', '.join(sorted(unknown))}"
                )

        # (3) Check age
        if last_verified:
            days = _days_since(last_verified)
            if days is not None and days > _STALENESS_DAYS:
                reasons.append(
                    f"last_verified {days} days ago (threshold: {_STALENESS_DAYS} days)"
                )

        if not reasons:
            continue

        staleness_flag = "; ".join(reasons)
        draft_id = _draft_id(f"stale:{entry_id_base}:{staleness_flag}")
        entries.append(DraftEntry(
            id=draft_id,
            knowledge=knowledge_text,
            why_it_matters="This knowledge entry may be outdated and needs review",
            applies_to=applies_to,
            agents=raw.get("agents", ["developer"]),
            tags=list(raw.get("tags", [])) + ["stale"],
            source="stale-flag",
            draft_reason=f"Staleness detected for entry {entry_id_base}",
            staleness_flag=staleness_flag,
            last_verified=last_verified,
        ))

    if entries:
        _merge_and_write(drafts_path, entries)

    return entries
