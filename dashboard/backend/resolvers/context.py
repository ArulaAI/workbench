"""Define Ceremony — Context Package resolver.

Implements intent declaration/refinement, context assembly from 7 sources,
persistence, and historical comparison queries.

See specs/tech/speed-define-ceremony-context.md for the full specification.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..paths import get_paths, SpeedPaths
from .ceremony_types import (
    AuditHistoryItem,
    CeremonyInfo,
    CeremonyState,
    CeremonyStatus,
    CodebaseItem,
    ContextPackage,
    DefectItem,
    Intent,
    KnowledgeItem,
    LearningItem,
    RelatedFeature,
    Revision,
    RevisionSummary,
    _load_ceremony_state,
    _read_json,
    _save_ceremony_state,
    _write_json,
    assert_ceremony_author,
    get_ceremony_info,
    get_current_actor,
)
from .context_types import (
    AssemblyStatus,
    ContextHistory,
    DeclareIntentResult,
    FeatureNameError,
    SourceStatus,
)

log = logging.getLogger("speed.dashboard.context")

# ── Validation ─────────────────────────────────────────────────

_FEATURE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$")
_CONSECUTIVE_HYPHENS_RE = re.compile(r"--")
_MAX_FEATURE_NAME_LEN = 50


def validate_feature_name(name: str) -> str:
    """Validate and normalize a feature name.

    Rules:
    - Non-empty
    - Lowercase alphanumeric and hyphens only
    - Cannot start or end with a hyphen
    - No consecutive hyphens
    - Max 50 characters

    Returns the validated name (stripped of whitespace).
    Raises FeatureNameError on failure.
    """
    name = name.strip()

    if not name:
        raise FeatureNameError("empty", "Feature name cannot be empty")

    if len(name) > _MAX_FEATURE_NAME_LEN:
        raise FeatureNameError(
            "too_long",
            f"Feature name must be {_MAX_FEATURE_NAME_LEN} characters or fewer (got {len(name)})",
        )

    if _CONSECUTIVE_HYPHENS_RE.search(name):
        raise FeatureNameError(
            "consecutive_hyphens",
            "Feature name cannot contain consecutive hyphens",
        )

    if not _FEATURE_NAME_RE.match(name):
        if name[0] == "-" or name[-1] == "-":
            raise FeatureNameError(
                "leading_trailing_hyphen",
                "Feature name cannot start or end with a hyphen",
            )
        raise FeatureNameError(
            "invalid_chars",
            "Feature name must be lowercase alphanumeric and hyphens only",
        )

    return name


def check_feature_name_collision(
    paths: SpeedPaths, feature_name: str
) -> str | None:
    """Check if a feature directory has an active ceremony.

    Returns the existing author name if collision exists, None if clear.
    A ceremony is 'active' if its current revision is DRAFTING or COMMITTED.
    """
    ceremony_path = paths.ceremony_state(feature_name)
    if not ceremony_path.exists():
        return None

    data = _read_json(ceremony_path)
    if data is None:
        return None

    # Check if the ceremony is in an active state
    current_rev_id = data.get("current_revision")
    revisions = data.get("revisions", {})
    if current_rev_id and current_rev_id in revisions:
        status = revisions[current_rev_id].get("status", "")
        if status in ("drafting", "committed"):
            return data.get("author", "unknown")

    return None


# ── Intent persistence ─────────────────────────────────────────


def _write_intent(paths: SpeedPaths, feature_name: str, intent: Intent) -> None:
    """Write intent.json to the ceremony directory."""
    _write_json(
        paths.ceremony_intent(feature_name),
        {
            "text": intent.text,
            "author": intent.author,
            "author_email": intent.author_email,
            "created_at": intent.created_at,
            "feature_name": intent.feature_name,
        },
    )


def _read_intent(paths: SpeedPaths, feature_name: str) -> Intent | None:
    """Read intent.json from the ceremony directory."""
    data = _read_json(paths.ceremony_intent(feature_name))
    if data is None:
        return None
    return Intent(
        text=data.get("text", ""),
        author=data.get("author", ""),
        author_email=data.get("author_email", ""),
        created_at=data.get("created_at", ""),
        feature_name=data.get("feature_name", ""),
    )


# ── Declare and refine intent ──────────────────────────────────


def create_ceremony(
    project_root: Path, text: str, feature_name: str,
) -> DeclareIntentResult:
    """Create ceremony artifacts (validate, write files). Fast, no assembly."""
    feature_name = validate_feature_name(feature_name)

    text = text.strip()
    if len(text) < 5:
        raise ValueError("Intent text must be at least 5 characters")

    paths = get_paths(project_root)

    existing_author = check_feature_name_collision(paths, feature_name)
    if existing_author is not None:
        raise FeatureNameError(
            "collision",
            f"Feature '{feature_name}' is already owned by {existing_author}",
        )

    name, email = get_current_actor()
    now = datetime.now(timezone.utc).isoformat()

    ceremony_dir = paths.ceremony_dir(feature_name)
    ceremony_dir.mkdir(parents=True, exist_ok=True)

    intent = Intent(
        text=text,
        author=name,
        author_email=email,
        created_at=now,
        feature_name=feature_name,
    )
    _write_intent(paths, feature_name, intent)
    _create_initial_ceremony(paths, feature_name, name, email, now)

    # Auto-claim the PRD for the caller. Design and RFC tabs stay unclaimed
    # and require an explicit claimSpec call — same flow for sole actors
    # and multi-actor rosters. Idempotent: skip if a claim file already
    # exists (repeated declareIntent on the same feature is a no-op here).
    from .ceremony_types import SpecClaim, load_spec_claim, save_spec_claim

    prd_claim_path = paths.ceremony_claim(feature_name, "prd")
    if load_spec_claim(prd_claim_path) is None:
        save_spec_claim(
            prd_claim_path,
            SpecClaim(
                spec_type="prd",
                claimant=name,
                claimant_email=email,
                claimed_at=now,
                last_activity_at=now,
                released_at=None,
            ),
        )

    ceremony_info = get_ceremony_info(project_root, feature_name)
    return DeclareIntentResult(
        feature_name=feature_name,
        context_package=None,
        ceremony=ceremony_info,  # type: ignore[arg-type]
    )


def declare_intent(
    project_root: Path, text: str, feature_name: str,
    sub_manager: Any = None, model: str | None = None, conn: Any = None,
) -> DeclareIntentResult:
    """Declare intent: create ceremony then assemble context (blocking).

    Used by tests and CLI. The schema mutation uses create_ceremony +
    background assembly instead, so subscription events arrive in real time.
    """
    result = create_ceremony(project_root, text, feature_name)

    pkg = assemble_context_package(
        project_root, text, feature_name,
        model=model, conn=conn, sub_manager=sub_manager,
    )

    ceremony_info = get_ceremony_info(project_root, feature_name)
    return DeclareIntentResult(
        feature_name=feature_name,
        context_package=pkg,
        ceremony=ceremony_info,  # type: ignore[arg-type]
    )


def refine_intent(
    project_root: Path, feature_name: str, text: str,
    sub_manager: Any = None, model: str | None = None, conn: Any = None,
) -> DeclareIntentResult:
    """Refine the intent for an existing ceremony.

    Updates intent.json text (preserves author and created_at),
    re-assembles the context package with the new scope.
    """
    text = text.strip()
    if len(text) < 5:
        raise ValueError("Intent text must be at least 5 characters")

    paths = get_paths(project_root)
    state_path = paths.ceremony_state(feature_name)

    if not state_path.exists():
        raise FileNotFoundError(f"No ceremony found for feature '{feature_name}'")

    # Ownership check
    state = _load_ceremony_state(state_path)
    _, email = get_current_actor()
    assert_ceremony_author(state, email)

    # Update intent text (preserve author and created_at)
    intent = _read_intent(paths, feature_name)
    if intent is None:
        raise FileNotFoundError(f"No intent.json for feature '{feature_name}'")

    updated_intent = Intent(
        text=text,
        author=intent.author,
        author_email=intent.author_email,
        created_at=intent.created_at,
        feature_name=intent.feature_name,
    )
    _write_intent(paths, feature_name, updated_intent)

    # Re-assemble context with new scope
    pkg = assemble_context_package(
        project_root, text, feature_name,
        model=model, conn=conn, sub_manager=sub_manager,
    )

    ceremony_info = get_ceremony_info(project_root, feature_name)
    return DeclareIntentResult(
        feature_name=feature_name,
        context_package=pkg,
        ceremony=ceremony_info,  # type: ignore[arg-type]
    )


def _create_initial_ceremony(
    paths: SpeedPaths,
    feature_name: str,
    author: str,
    author_email: str,
    now: str,
) -> None:
    """Create ceremony.json with the first revision at DRAFTING."""
    import hashlib

    # Initial revision with zero hashes (no artifacts exist yet)
    zero_hash = "0" * 64
    content = zero_hash + zero_hash + zero_hash + ""
    revision_id = hashlib.sha256(content.encode()).hexdigest()[:8]

    state = CeremonyState(
        feature_name=feature_name,
        author=author,
        author_email=author_email,
        created_at=now,
        is_multiplayer=(paths.root / ".speed" / "shared").is_dir(),
        current_revision=revision_id,
        revision_count=1,
        revisions={
            revision_id: Revision(
                revision_id=revision_id,
                parent_id=None,
                status=CeremonyStatus.DRAFTING,
                spec_content_hash=zero_hash,
                context_package_hash=zero_hash,
                validation_hash=zero_hash,
                created_at=now,
                reason=None,
            )
        },
        reflog=[],
    )
    _save_ceremony_state(paths.ceremony_state(feature_name), state)


# ── CSG Scoping ────────────────────────────────────────────────

_STOP_WORDS = frozenset(
    "a an the to by for in on of is it be at as or and with from that this"
    " which have has had do does did will would can could should shall may"
    " might must not no but if so than too very just also how what where"
    " when who why all each every both few more most other some such any"
    " want need able".split()
)


def scope_csg_nodes(
    intent: str,
    graph_path: Path,
    *,
    use_llm: bool = True,
    model: str | None = None,
    conn: Any = None,
    project_root: Any = None,
) -> tuple[list[str], bool]:
    """Scope the semantic graph to nodes relevant to the author's intent.

    Strategy:
    1. If use_llm is True and a model is available, ask the LLM to select
       seed files directly from the project file list. Map those to node IDs.
    2. Fall back to keyword tokenization + word-boundary matching.
    3. If no matches, return all nodes (full-graph fallback) with low_confidence=True.

    Returns (matching_node_ids, low_confidence).
    """
    if not graph_path.exists():
        return [], False

    try:
        data = json.loads(graph_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        log.warning("Failed to read semantic graph at %s", graph_path)
        return [], False

    nodes = data.get("nodes", [])
    if not nodes:
        return [], False

    # Resolve model from ceremony config if caller didn't provide one
    if model is None and use_llm:
        try:
            from ..llm import get_ceremony_models
            ceremony = get_ceremony_models(project_root)
            if ceremony:
                model = ceremony[0]["id"]
        except Exception:
            pass

    # Primary path: LLM seed file selection
    if use_llm and model is not None:
        try:
            seed_files = _llm_select_seed_files(
                intent, nodes, model=model, conn=conn, project_root=project_root,
            )
            if seed_files:
                seed_set = set(seed_files)
                matched = [n["id"] for n in nodes if n.get("file") in seed_set and n.get("id")]
                if matched:
                    log.info("LLM seed scoping: %d seeds → %d nodes", len(seed_files), len(matched))
                    return matched, False
        except Exception:
            log.warning("LLM seed scoping failed, falling back to keyword matching", exc_info=True)

    # Fallback: keyword matching with word boundaries
    tokens = _keyword_tokens(intent)
    if not tokens:
        all_ids = [n.get("id", "") for n in nodes if n.get("id")]
        return all_ids, True

    matched_ids: list[str] = []
    for node in nodes:
        node_id = node.get("id", "")
        if not node_id:
            continue
        # Build searchable words (not raw string) for word-boundary matching
        searchable_words = set()
        for field in ("name", "description", "file", "kind"):
            for word in re.split(r"[^a-zA-Z0-9]+", str(node.get(field, "")).lower()):
                if word:
                    searchable_words.add(word)

        if tokens & searchable_words:
            matched_ids.append(node_id)

    if not matched_ids:
        all_ids = [n.get("id", "") for n in nodes if n.get("id")]
        return all_ids, True

    return matched_ids, len(matched_ids) > len(nodes) * 0.4


def _llm_select_seed_files(
    intent: str,
    nodes: list[dict],
    *,
    model: str | None = None,
    conn: Any = None,
    project_root: Any = None,
) -> list[str] | None:
    """Ask the LLM to select seed files from the project file list.

    Returns a list of file paths, or None if unavailable.
    """
    try:
        from ..llm import llm_complete
        from ..llm.models import SeedFiles
    except ImportError:
        return None

    if model is None:
        return None

    # Build deduplicated file list from graph nodes
    all_files = sorted(set(n.get("file", "") for n in nodes if n.get("file")))
    if not all_files:
        return None

    file_list = "\n".join(all_files)

    result: SeedFiles = llm_complete(
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a codebase scoping assistant. Given a feature intent and a "
                    "list of all files in the project, identify the seed files directly "
                    "relevant to implementing this feature. Be precise: include integration "
                    "points, pattern references, data sources, and core infrastructure. "
                    "Exclude test files, language fixture files, and unrelated scripts."
                ),
            },
            {
                "role": "user",
                "content": f"Feature intent:\n{intent}\n\nAll files in project:\n{file_list}",
            },
        ],
        response_model=SeedFiles,
        model=model,
        temperature=0.1,
        max_tokens=4096,
        conn=conn,
        purpose="intent_seed_scoping",
        project_root=project_root,
    )

    # Validate returned paths against actual files
    valid_files = set(all_files)
    seeds = [f for f in result.seeds if f in valid_files]
    log.info("LLM seed selection: %d returned, %d valid. Reasoning: %s",
             len(result.seeds), len(seeds), result.reasoning[:200])
    return seeds if seeds else None


def _keyword_tokens(intent: str) -> set[str]:
    """Tokenize intent into keyword set for fallback matching."""
    tokens: set[str] = set()
    for word in re.split(r"\W+", intent.lower()):
        if word and word not in _STOP_WORDS and len(word) > 1:
            tokens.add(word)
    return tokens


# ── Source Readers ─────────────────────────────────────────────


def read_codebase_context(
    paths: SpeedPaths, scoped_nodes: list[str]
) -> list[CodebaseItem]:
    """Read semantic graph nodes matching the scoped_area."""
    graph_path = paths.root / ".speed" / "context" / "semantic-graph.json"
    if not graph_path.exists():
        return []

    try:
        data = json.loads(graph_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    scoped_set = set(scoped_nodes)
    items: list[CodebaseItem] = []

    for node in data.get("nodes", []):
        node_id = node.get("id", "")
        if node_id in scoped_set:
            name = node.get("name", "")
            kind = node.get("kind", "")
            desc = node.get("description", "")
            # Build a useful description: "function detect_platform" or the
            # node's own description if it has one.
            if desc:
                label = desc
            elif name and kind:
                label = f"{kind} {name}"
            else:
                label = kind or name

            items.append(
                CodebaseItem(
                    path=node.get("file", name),
                    description=label,
                    node_ids=[node_id],
                )
            )

    return items


def _extract_observation_text(detail: dict, obs_type: str) -> str:
    """Extract a human-readable display string from an observation detail dict.

    Covers all known observation_type schemas:
    - reviewer_finding: finding (with category prefix)
    - security_finding: title
    - agent_concern: concern
    - retry: what_happened
    - coherence_issue: description (with issue_type prefix)
    - verify_finding: requirement + analysis
    - context_miss: file + reason
    - decomposition_miss: issue + analysis
    - human_override: change_type + guidance/findings summary
    - success: duration + file counts (skip — not useful as a learning)
    - unattributed_changes: skip — not useful
    """
    # Direct text fields, tried in priority order
    for key in ("finding", "concern", "what_happened", "title", "message"):
        val = detail.get(key, "")
        if val and isinstance(val, str):
            cat = detail.get("category", "")
            if cat and cat not in ("unclassified", ""):
                return f"[{cat}] {val}"
            return val

    # Description-based types (coherence_issue, etc.)
    desc = detail.get("description", "")
    if desc:
        issue_type = detail.get("issue_type", "")
        if issue_type:
            return f"[{issue_type}] {desc}"
        return desc

    # Verify findings: requirement + analysis
    req = detail.get("requirement", "")
    analysis = detail.get("analysis", "")
    if req:
        return f"{req}: {analysis}" if analysis else req

    # Context miss: file + reason
    file_val = detail.get("file", "")
    reason = detail.get("reason", "")
    if file_val and reason:
        return f"{file_val}: {reason}"

    # Human override: summarize the change
    change_type = detail.get("change_type", "")
    guidance = detail.get("guidance_text", "")
    if change_type and guidance:
        return f"[{change_type}] {guidance}"
    if change_type == "forced_approval":
        verdict = detail.get("reviewer_verdict", "")
        return f"Forced approval (reviewer said: {verdict})" if verdict else "Forced approval"

    # Decomposition miss
    issue = detail.get("issue", "")
    if issue and analysis:
        return f"[{issue}] {analysis}"

    # Nothing useful — skip rather than dump JSON
    return ""


def read_learnings(
    paths: SpeedPaths, scoped_files: list[str], intent: str = ""
) -> list[LearningItem]:
    """Read observations filtered by TF-IDF similarity to the intent.

    Uses the same approach as related_specs.py: compute cosine similarity
    between the intent text and each observation's content, keep only
    observations above a relevance threshold.
    """
    obs_dir = paths.root / ".speed" / "shared" / "knowledge" / "observations"
    if not obs_dir.is_dir():
        obs_dir = paths.root / ".speed" / "memory" / "observations"
        if not obs_dir.is_dir():
            return []

    # Collect all observations with their text
    candidates: list[tuple[str, str, str, str]] = []  # (text, display_text, source_feature, confidence)

    for jsonl_file in obs_dir.glob("*.jsonl"):
        source_feature = jsonl_file.stem
        try:
            for line in jsonl_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obs = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Extract display text from the detail dict
                detail = obs.get("detail", {})
                if isinstance(detail, dict):
                    display = _extract_observation_text(detail, obs.get("observation_type", ""))
                else:
                    display = str(detail)

                obs_text = obs.get("text", obs.get("observation", ""))
                if obs_text:
                    display = obs_text

                # Build searchable text: feature name + observation type + display text
                search_text = f"{source_feature} {obs.get('observation_type', '')} {display}"

                confidence = obs.get("confidence", obs.get("weight", "medium"))
                if isinstance(confidence, (int, float)):
                    confidence = "high" if confidence >= 0.7 else "medium" if confidence >= 0.4 else "low"

                if display:
                    candidates.append((search_text, display, source_feature, confidence))
        except OSError:
            continue

    if not candidates or not intent:
        return []

    # TF-IDF cosine similarity against the intent
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        all_docs = [intent] + [c[0] for c in candidates]
        vectorizer = TfidfVectorizer(sublinear_tf=True, stop_words="english")
        tfidf_matrix = vectorizer.fit_transform(all_docs)
        similarities = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:]).flatten()

        # Keep observations above threshold, sorted by score
        THRESHOLD = 0.05
        scored = [(sim, candidates[i]) for i, sim in enumerate(similarities) if sim >= THRESHOLD]
        scored.sort(key=lambda x: -x[0])

        items: list[LearningItem] = []
        for _score, (_, display, source_feature, confidence) in scored:
            items.append(
                LearningItem(
                    text=display,
                    source_feature=source_feature,
                    confidence=confidence,
                )
            )
        return items

    except ImportError:
        log.warning("sklearn not available, returning all observations unfiltered")
        return [
            LearningItem(text=c[1], source_feature=c[2], confidence=c[3])
            for c in candidates
        ]


def read_defects(
    paths: SpeedPaths, scoped_files: list[str], feature_name: str = ""
) -> list[DefectItem]:
    """Read defects filtered by scoped file paths and feature relevance."""
    items: list[DefectItem] = []
    scoped_set = set(scoped_files)
    severity_map = {"P0": "critical", "P1": "critical", "P2": "major", "P3": "minor"}

    # Build a set of scope keywords from the scoped file paths for fuzzy matching
    scope_terms = set()
    for f in scoped_files:
        for part in re.split(r"[/._\-]", f.lower()):
            if part and len(part) > 2:
                scope_terms.add(part)

    # Source 1: .speed/defects/*/state.json
    defects_dir = paths.defects_dir
    if defects_dir.is_dir():
        for state_file in defects_dir.glob("*/state.json"):
            data = _read_json(state_file)
            if data is None:
                continue

            related = data.get("related_files", [])
            if isinstance(related, str):
                related = [related]

            # Filter: require file overlap when related_files is populated
            if scoped_set and related:
                if not any(f in scoped_set for f in related):
                    continue
            # Skip defects with no related_files (can't verify relevance)
            elif scoped_set and not related:
                continue

            severity = data.get("severity", "minor")
            severity = severity_map.get(severity, severity)

            items.append(
                DefectItem(
                    name=data.get("name", state_file.parent.name),
                    severity=severity,
                    status=data.get("status", "open"),
                    related_files=related,
                )
            )

    # Source 2: specs/defects/*.md — parse metadata for scope filtering
    specs_dir = paths.root / "specs" / "defects"
    if specs_dir.is_dir():
        seen = {d.name for d in items}
        for md_file in sorted(specs_dir.glob("*.md")):
            name = md_file.stem
            if name in seen:
                continue

            severity = "minor"
            related_feature = ""
            tags: list[str] = []
            related_files: list[str] = []
            try:
                for line in md_file.read_text(encoding="utf-8").splitlines()[:20]:
                    low = line.strip().lower()
                    if low.startswith("severity:"):
                        val = line.split(":", 1)[1].strip().lower()
                        if val in ("critical", "major", "minor"):
                            severity = val
                        elif val.upper() in severity_map:
                            severity = severity_map[val.upper()]
                    elif low.startswith("related feature:"):
                        related_feature = line.split(":", 1)[1].strip().lower()
                    elif low.startswith("tags:"):
                        tags = [t.strip().lower() for t in line.split(":", 1)[1].split(",")]
                    elif low.startswith("related files:") or low.startswith("affected files:"):
                        related_files = [f.strip() for f in line.split(":", 1)[1].split(",") if f.strip()]
            except OSError:
                pass

            # Filter by relevance to scoped area
            if scoped_set:
                relevant = False
                # Check related_files overlap
                if related_files and any(f in scoped_set for f in related_files):
                    relevant = True
                # Check if related feature terms overlap with scope terms
                elif related_feature:
                    feature_words = set(re.split(r"[,\s/._\-]+", related_feature))
                    if feature_words & scope_terms:
                        relevant = True
                # Check if tags overlap with scope terms
                elif tags:
                    if set(tags) & scope_terms:
                        relevant = True
                if not relevant:
                    continue

            items.append(
                DefectItem(
                    name=name,
                    severity=severity,
                    status="open",
                    related_files=related_files,
                )
            )

    # Sort by severity: critical first
    severity_order = {"critical": 0, "major": 1, "minor": 2}
    items.sort(key=lambda d: severity_order.get(d.severity, 2))
    return items


def read_project_knowledge(paths: SpeedPaths) -> list[KnowledgeItem]:
    """Read curated conventions from project knowledge. Global, not scoped."""
    # Try multiplayer path first, then single-player
    knowledge_path = paths.root / ".speed" / "shared" / "knowledge" / "conventions.json"
    if not knowledge_path.exists():
        knowledge_path = paths.root / ".speed" / "memory" / "project-knowledge.json"
        if not knowledge_path.exists():
            return []

    data = _read_json(knowledge_path)
    if data is None:
        return []

    items: list[KnowledgeItem] = []

    # Handle both list and dict formats
    conventions = data if isinstance(data, list) else data.get("conventions", data.get("items", []))
    if isinstance(conventions, dict):
        conventions = list(conventions.values()) if conventions else []

    for entry in conventions:
        if isinstance(entry, dict):
            text = entry.get("text", entry.get("pattern", entry.get("convention", "")))
            confidence = entry.get("confidence", "medium")
            source = entry.get("source", "observation")
            if text:
                items.append(KnowledgeItem(text=text, confidence=confidence, source=source))

    confidence_order = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda x: confidence_order.get(x.confidence, 2))
    return items


def read_vision(project_root: Path) -> tuple[str, str | None]:
    """Read product vision status and content.

    Returns (vision_status, vision_content):
    - ("available", content) — substantive content
    - ("stale", content) — template or too short
    - ("missing", None) — file doesn't exist
    """
    overview = project_root / "specs" / "product" / "overview.md"
    if not overview.exists():
        return "missing", None

    try:
        content = overview.read_text(encoding="utf-8").strip()
    except OSError:
        return "missing", None

    if len(content) < 50:
        return "stale", content

    # Check if it's just headings/template markers
    template_markers = ("{{", "<!-- TODO", "[TODO]", "[PLACEHOLDER]", "TODO:", "<!-- FILL")
    non_empty_lines = [line.strip() for line in content.splitlines() if line.strip()]
    substantive = [
        line
        for line in non_empty_lines
        if not line.startswith("#")
        and not any(line.startswith(m) for m in template_markers)
    ]

    if not substantive:
        return "stale", content

    return "available", content


def read_related_features(
    paths: SpeedPaths, scoped_files: list[str], current_feature: str
) -> list[RelatedFeature]:
    """Find other features with shared file paths.

    Primary: check context-package.json from prior ceremonies.
    Fallback: aggregate files_touched from task JSON files.
    """
    if not scoped_files:
        return []

    scoped_set = set(scoped_files)
    items: list[RelatedFeature] = []

    for name in paths.feature_names():
        if name == current_feature:
            continue

        other_files: set[str] = set()

        # Primary: context package from a prior ceremony
        pkg_path = paths.ceremony_context_package(name)
        if pkg_path.exists():
            pkg_data = _read_json(pkg_path)
            if pkg_data:
                for cb in pkg_data.get("codebase", []):
                    path = cb.get("path", "")
                    if path:
                        other_files.add(path)

        # Fallback: aggregate files_touched from task JSONs
        if not other_files:
            tasks_dir = paths.feature_shared(name) / "tasks"
            if tasks_dir.is_dir():
                for task_file in tasks_dir.glob("*.json"):
                    task_data = _read_json(task_file)
                    if task_data is None:
                        continue
                    touched = task_data.get("files_touched", [])
                    if isinstance(touched, list):
                        other_files.update(f for f in touched if isinstance(f, str))

        overlap = list(scoped_set & other_files)
        if not overlap:
            continue

        # Read ceremony state if it exists, otherwise mark as "completed"
        state_path = paths.ceremony_state(name)
        state_str = "completed"
        if state_path.exists():
            state_data = _read_json(state_path)
            if state_data:
                cur_rev_id = state_data.get("current_revision", "")
                revisions = state_data.get("revisions", {})
                if cur_rev_id in revisions:
                    state_str = revisions[cur_rev_id].get("status", "completed")

        items.append(
            RelatedFeature(name=name, state=state_str, overlap_files=overlap)
        )

    return items


def read_audit_history(
    paths: SpeedPaths, scoped_area: list[str]
) -> list[AuditHistoryItem]:
    """Read audit findings from past spec audits.

    Reads plan-audit-*.json files (structured audit results with issues array).
    These files may be wrapped in markdown code fences from the audit pipeline.
    """
    items: list[AuditHistoryItem] = []
    severity_map = {"error": "critical", "warning": "major", "info": "info"}

    for name in paths.feature_names():
        logs_dir = paths.feature_local(name) / "logs"
        if not logs_dir.is_dir():
            continue

        # Read plan-audit-*.json files (structured audit results)
        for audit_file in logs_dir.glob("plan-audit-*.json"):
            try:
                raw = audit_file.read_text(encoding="utf-8").strip()

                # Strip markdown code fences if present
                if raw.startswith("```"):
                    lines = raw.splitlines()
                    # Remove first line (```json) and last line (```)
                    inner = []
                    started = False
                    for line in lines:
                        stripped = line.strip()
                        if not started and stripped.startswith("```"):
                            started = True
                            continue
                        if started and stripped == "```":
                            break
                        if started:
                            inner.append(line)
                    raw = "\n".join(inner)

                entry = json.loads(raw)

                spec_file = entry.get("spec_file", "")
                spec_type = entry.get("spec_type", "")

                for issue in entry.get("issues", []):
                    sev = issue.get("severity", "info").lower()
                    sev = severity_map.get(sev, sev)
                    finding = issue.get("message", issue.get("finding", ""))
                    section = issue.get("section", "")
                    if finding:
                        items.append(
                            AuditHistoryItem(
                                feature_name=name,
                                finding=finding,
                                severity=sev,
                                section=f"{spec_type}: {section}" if spec_type else section,
                            )
                        )
            except (OSError, json.JSONDecodeError):
                continue

    # Sort by severity
    severity_order = {"critical": 0, "major": 1, "minor": 2, "info": 3}
    items.sort(key=lambda x: severity_order.get(x.severity, 3))
    return items


# ── BLUF Synthesis ─────────────────────────────────────────────


def synthesize_bluf(
    pkg: "ContextPackage",
    *,
    model: str | None = None,
    conn: Any = None,
    project_root: Any = None,
) -> str | None:
    """Generate an LLM-synthesized intelligence brief from the assembled context.

    Returns a 2-3 paragraph summary highlighting: critical defects in the area,
    high-confidence learnings from past features, related features and file
    overlap, vision alignment status, and audit findings. Written as an
    actionable brief for someone about to write a spec.
    """
    if model is None:
        return None

    try:
        from ..llm import llm_complete
    except ImportError:
        return None

    from pydantic import BaseModel, Field

    class BlufSummary(BaseModel):
        summary: str = Field(description="2-3 paragraph intelligence brief for the spec author")

    # Build a compact representation of the context for the LLM
    lines: list[str] = []
    lines.append(f"Intent: {pkg.intent}")
    lines.append(f"Feature: {pkg.feature_name}")

    unique_files = sorted(set(c.path for c in pkg.codebase))
    lines.append(f"\nScoped to {len(unique_files)} files across {len(pkg.scoped_area)} symbols.")

    if pkg.defects:
        lines.append(f"\nDefects in this area ({len(pkg.defects)}):")
        for d in pkg.defects:
            lines.append(f"  [{d.severity}] {d.name}")

    if pkg.learnings:
        lines.append(f"\nLearnings from past features ({len(pkg.learnings)}):")
        for l in pkg.learnings[:10]:  # cap to keep prompt manageable
            lines.append(f"  [{l.confidence}] {l.text[:150]}")
        if len(pkg.learnings) > 10:
            lines.append(f"  ... and {len(pkg.learnings) - 10} more")

    if pkg.related_features:
        lines.append(f"\nRelated features ({len(pkg.related_features)}):")
        for r in pkg.related_features:
            lines.append(f"  {r.name} ({r.state}, {len(r.overlap_files)} shared files)")

    if pkg.audit_history:
        lines.append(f"\nAudit findings ({len(pkg.audit_history)}):")
        for a in pkg.audit_history:
            lines.append(f"  [{a.severity}] {a.finding[:150]}")

    lines.append(f"\nVision status: {pkg.vision_status}")
    lines.append(f"Project knowledge: {len(pkg.project_knowledge)} conventions")

    context_text = "\n".join(lines)

    try:
        result: BlufSummary = llm_complete(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a technical writing assistant. Given assembled context "
                        "about a codebase area, write a concise intelligence brief (2-3 "
                        "paragraphs) for someone about to write a spec for a new feature. "
                        "Focus on what matters most: blockers, risks, patterns to follow, "
                        "things the author needs to know. Be direct and specific. Reference "
                        "actual file names, defect names, and feature names. Do not use "
                        "filler or hedging language."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Write the intelligence brief for this context:\n\n{context_text}",
                },
            ],
            response_model=BlufSummary,
            model=model,
            temperature=0.3,
            max_tokens=1024,
            conn=conn,
            purpose="bluf_synthesis",
            project_root=project_root,
        )
        return result.summary
    except Exception:
        log.warning("BLUF synthesis failed", exc_info=True)
        return None


# ── Assembly ───────────────────────────────────────────────────


def _emit(sub_manager: Any, feature: str, source: str, status: str, error: str | None = None) -> None:
    """Publish a context assembly progress event if a sub_manager is available."""
    if sub_manager is None:
        return
    from ..subscriptions import DashboardEvent, EventType
    event = DashboardEvent(
        type=EventType.CONTEXT_ASSEMBLY_PROGRESS,
        feature=feature,
        payload={"source": source, "status": status, "error": error},
    )
    sub_manager.publish_sync(event)


def assemble_context_package(
    project_root: Path,
    intent: str,
    feature_name: str,
    *,
    model: str | None = None,
    conn: Any = None,
    sub_manager: Any = None,
) -> ContextPackage:
    """Assemble a scoped context package from 7 sources.

    Each reader runs independently. A failure in one does not affect others.
    The sources_status dict records per-source outcome.
    Emits per-source progress events via sub_manager when available.
    """
    paths = get_paths(project_root)
    now = datetime.now(timezone.utc).isoformat()
    sources_status: dict[str, str] = {}

    # 1. Scope the semantic graph (LLM seed selection when available)
    graph_path = paths.root / ".speed" / "context" / "semantic-graph.json"
    scoped_nodes, low_confidence = scope_csg_nodes(intent, graph_path, model=model, conn=conn, project_root=project_root)

    # Determine which scoping method was used
    if low_confidence and scoped_nodes:
        scoping_method = "full_graph"
    elif model is not None:
        scoping_method = "llm"
    else:
        scoping_method = "keyword"

    # 2. Read codebase context to derive scoped file paths
    codebase: list[CodebaseItem] = []
    try:
        codebase = read_codebase_context(paths, scoped_nodes)
        sources_status["codebase"] = "ok" if codebase else "empty"
    except Exception as exc:
        log.exception("Failed to read codebase context")
        sources_status["codebase"] = "error"
    _emit(sub_manager, feature_name, "codebase", sources_status["codebase"])

    scoped_files = [item.path for item in codebase]

    # 3. Read remaining 6 sources
    learnings: list[LearningItem] = []
    try:
        learnings = read_learnings(paths, scoped_files, intent)
        sources_status["learnings"] = "ok" if learnings else "empty"
    except Exception:
        log.exception("Failed to read learnings")
        sources_status["learnings"] = "error"
    _emit(sub_manager, feature_name, "learnings", sources_status["learnings"])

    defects: list[DefectItem] = []
    try:
        defects = read_defects(paths, scoped_files, feature_name)
        sources_status["defects"] = "ok" if defects else "empty"
    except Exception:
        log.exception("Failed to read defects")
        sources_status["defects"] = "error"
    _emit(sub_manager, feature_name, "defects", sources_status["defects"])

    knowledge: list[KnowledgeItem] = []
    try:
        knowledge = read_project_knowledge(paths)
        sources_status["project_knowledge"] = "ok" if knowledge else "empty"
    except Exception:
        log.exception("Failed to read project knowledge")
        sources_status["project_knowledge"] = "error"
    _emit(sub_manager, feature_name, "project_knowledge", sources_status["project_knowledge"])

    vision_status_val = "missing"
    vision_content_val: str | None = None
    try:
        vision_status_val, vision_content_val = read_vision(project_root)
        sources_status["vision"] = "ok" if vision_status_val != "missing" else "empty"
    except Exception:
        log.exception("Failed to read vision")
        sources_status["vision"] = "error"
    _emit(sub_manager, feature_name, "vision", sources_status["vision"])

    related: list[RelatedFeature] = []
    try:
        related = read_related_features(paths, scoped_files, feature_name)
        sources_status["related_features"] = "ok" if related else "empty"
    except Exception:
        log.exception("Failed to read related features")
        sources_status["related_features"] = "error"
    _emit(sub_manager, feature_name, "related_features", sources_status["related_features"])

    audit: list[AuditHistoryItem] = []
    try:
        audit = read_audit_history(paths, scoped_nodes)
        sources_status["audit_history"] = "ok" if audit else "empty"
    except Exception:
        log.exception("Failed to read audit history")
        sources_status["audit_history"] = "error"
    _emit(sub_manager, feature_name, "audit_history", sources_status["audit_history"])

    # 4. Build the package
    pkg = ContextPackage(
        intent=intent,
        feature_name=feature_name,
        scoped_area=scoped_nodes,
        codebase=codebase,
        learnings=learnings,
        defects=defects,
        project_knowledge=knowledge,
        vision_status=vision_status_val,
        vision_content=vision_content_val,
        related_features=related,
        audit_history=audit,
        assembled_at=now,
        sources_status=sources_status,
        scoping_method=scoping_method,
        low_confidence=low_confidence,
    )

    # 5. Persist (before synthesis so navigation isn't blocked)
    persist_context_package(project_root, feature_name, pkg)

    # 6. Signal completion (unblocks frontend navigation)
    _emit(sub_manager, feature_name, "complete", "ok")

    # 7. Synthesize BLUF summary (runs after navigation, updates persisted package)
    try:
        pkg.bluf_summary = synthesize_bluf(
            pkg, model=model, conn=conn, project_root=project_root,
        )
        if pkg.bluf_summary:
            persist_context_package(project_root, feature_name, pkg)
    except Exception:
        log.warning("BLUF synthesis failed", exc_info=True)

    return pkg


# ── Persistence ────────────────────────────────────────────────


def persist_context_package(
    project_root: Path, feature_name: str, pkg: ContextPackage
) -> Path:
    """Write ContextPackage to .speed/features/{feature}/context-package.json."""
    paths = get_paths(project_root)
    out_path = paths.ceremony_context_package(feature_name)

    data: dict[str, Any] = {
        "intent": pkg.intent,
        "feature_name": pkg.feature_name,
        "scoped_area": pkg.scoped_area,
        "codebase": [
            {"path": c.path, "description": c.description, "node_ids": c.node_ids}
            for c in pkg.codebase
        ],
        "learnings": [
            {"text": l.text, "source_feature": l.source_feature, "confidence": l.confidence}
            for l in pkg.learnings
        ],
        "defects": [
            {"name": d.name, "severity": d.severity, "status": d.status, "related_files": d.related_files}
            for d in pkg.defects
        ],
        "project_knowledge": [
            {"text": k.text, "confidence": k.confidence, "source": k.source}
            for k in pkg.project_knowledge
        ],
        "vision_status": pkg.vision_status,
        "vision_content": pkg.vision_content,
        "related_features": [
            {"name": r.name, "state": r.state, "overlap_files": r.overlap_files}
            for r in pkg.related_features
        ],
        "audit_history": [
            {"feature_name": a.feature_name, "finding": a.finding, "severity": a.severity, "section": a.section}
            for a in pkg.audit_history
        ],
        "assembled_at": pkg.assembled_at,
        "sources_status": pkg.sources_status,
        "scoping_method": pkg.scoping_method,
        "low_confidence": pkg.low_confidence,
        "bluf_summary": pkg.bluf_summary,
    }

    _write_json(out_path, data)
    return out_path


def load_context_package(
    project_root: Path, feature_name: str
) -> ContextPackage | None:
    """Load a previously persisted context package.

    Returns None if the file doesn't exist or is malformed.
    Handles schema evolution: missing fields default to empty.
    """
    paths = get_paths(project_root)
    pkg_path = paths.ceremony_context_package(feature_name)

    data = _read_json(pkg_path)
    if data is None:
        return None

    try:
        return ContextPackage(
            intent=data.get("intent", ""),
            feature_name=data.get("feature_name", feature_name),
            scoped_area=data.get("scoped_area", []),
            codebase=[
                CodebaseItem(
                    path=c.get("path", ""),
                    description=c.get("description", ""),
                    node_ids=c.get("node_ids", []),
                )
                for c in data.get("codebase", [])
            ],
            learnings=[
                LearningItem(
                    text=l.get("text", ""),
                    source_feature=l.get("source_feature", ""),
                    confidence=l.get("confidence", "medium"),
                )
                for l in data.get("learnings", [])
            ],
            defects=[
                DefectItem(
                    name=d.get("name", ""),
                    severity=d.get("severity", "minor"),
                    status=d.get("status", "open"),
                    related_files=d.get("related_files", []),
                )
                for d in data.get("defects", [])
            ],
            project_knowledge=[
                KnowledgeItem(
                    text=k.get("text", ""),
                    confidence=k.get("confidence", "medium"),
                    source=k.get("source", "observation"),
                )
                for k in data.get("project_knowledge", [])
            ],
            vision_status=data.get("vision_status", "missing"),
            vision_content=data.get("vision_content"),
            related_features=[
                RelatedFeature(
                    name=r.get("name", ""),
                    state=r.get("state", "drafting"),
                    overlap_files=r.get("overlap_files", []),
                )
                for r in data.get("related_features", [])
            ],
            audit_history=[
                AuditHistoryItem(
                    feature_name=a.get("feature_name", ""),
                    finding=a.get("finding", ""),
                    severity=a.get("severity", "info"),
                    section=a.get("section", ""),
                )
                for a in data.get("audit_history", [])
            ],
            assembled_at=data.get("assembled_at", ""),
            sources_status=data.get("sources_status", {}),
            scoping_method=data.get("scoping_method", "keyword"),
            low_confidence=data.get("low_confidence", False),
            bluf_summary=data.get("bluf_summary"),
        )
    except Exception:
        log.exception("Failed to parse context package for %s", feature_name)
        return None


# ── Query resolvers ────────────────────────────────────────────


def get_context_package(
    project_root: Path, feature_name: str
) -> ContextPackage | None:
    """Query resolver: return the persisted context package."""
    return load_context_package(project_root, feature_name)


def get_context_assembly_status(
    project_root: Path, feature_name: str
) -> AssemblyStatus:
    """Query resolver: return per-source assembly status."""
    pkg = load_context_package(project_root, feature_name)
    if pkg is None:
        return AssemblyStatus(status="idle", sources=[])

    sources = [
        SourceStatus(
            name=name,
            status=status,
            error=None if status != "error" else f"{name} source failed",
        )
        for name, status in (pkg.sources_status or {}).items()
    ]

    return AssemblyStatus(status="complete", sources=sources)


def get_context_history(
    project_root: Path, feature_name: str
) -> ContextHistory | None:
    """Query resolver: return snapshot vs. current comparison.

    Loads the persisted snapshot and re-assembles current context
    for the same scoped area.
    """
    paths = get_paths(project_root)

    # Load the snapshot
    snapshot = load_context_package(project_root, feature_name)
    if snapshot is None:
        return None

    # Read the intent to re-assemble with the same text
    intent = _read_intent(paths, feature_name)
    if intent is None:
        return ContextHistory(
            snapshot=snapshot,
            current=None,
            current_assembly_status="error",
            current_assembly_error="No intent.json found for this feature",
            ceremony=get_ceremony_info(project_root, feature_name),
        )

    # Re-assemble current context
    current: ContextPackage | None = None
    current_status = "ok"
    current_error: str | None = None

    try:
        current = assemble_context_package(
            project_root, intent.text, feature_name
        )
    except Exception as exc:
        log.exception("Failed to assemble current context for %s", feature_name)
        current_status = "error"
        current_error = str(exc)

    return ContextHistory(
        snapshot=snapshot,
        current=current,
        current_assembly_status=current_status,
        current_assembly_error=current_error,
        ceremony=get_ceremony_info(project_root, feature_name),
    )
