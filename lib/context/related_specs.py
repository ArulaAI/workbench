"""Related Spec Compression — multi-signal relevance scoring + budget assembly.

Determines which specs are relevant to the primary feature using:
  Signal 1: TF-IDF cosine similarity via sklearn (works on any markdown)
  Signal 2: Structural boosters (front-matter, cross-refs, dependency headers, filename pairing)
  Assembly: Budget-constrained selection (highest score first, whole specs only)

Replaces raw concatenation in lib/cmd/plan.sh's _gather_related_specs.

Usage:
    from lib.context.related_specs import score_and_assemble_specs
"""

from __future__ import annotations

import os
import re
import sys

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .utils import estimate_tokens_from_text


# ── Front-matter Parsing ─────────────────────────────────────


def _parse_front_matter(primary_spec_texts: dict[str, str]) -> set[str]:
    """Extract related spec paths from YAML front-matter in primary specs.

    Scans each primary spec for a YAML block delimited by --- lines at the
    start of the file. Within that block, looks for a `related:` key with
    a list of paths.

    Returns:
        Set of declared paths (normalized, possibly empty).
    """
    declared: set[str] = set()
    fm_re = re.compile(r"\A---\s*\n(.*?)\n---", re.DOTALL)

    for _path, content in primary_spec_texts.items():
        match = fm_re.match(content)
        if not match:
            continue
        fm_block = match.group(1)
        in_related = False
        for line in fm_block.splitlines():
            stripped = line.strip()
            if stripped.startswith("related:"):
                in_related = True
                continue
            if in_related:
                if stripped.startswith("- "):
                    path = stripped[2:].strip().strip("'\"")
                    if path:
                        declared.add(os.path.normpath(path))
                elif stripped and not stripped.startswith("#"):
                    break  # Next YAML key
    return declared


# ── TF-IDF Scoring (sklearn) ──────────────────────────────────


def _compute_tfidf_scores(
    primary_texts: list[str],
    related_texts: dict[str, str],
) -> dict[str, float]:
    """Compute TF-IDF cosine similarity between primary specs and each candidate.

    Uses sklearn's TfidfVectorizer with:
      - sublinear_tf=True: dampens repeated terms (1 + log(tf))
      - stop_words="english": filters generic terms
      - smooth_idf=True: prevents division-by-zero (default)
      - L2 normalization: length-independent comparison

    Args:
        primary_texts: list of content strings for the primary spec triad
        related_texts: {path: content} for candidate related specs

    Returns:
        {path: similarity_score} where score is 0.0 to 1.0
    """
    if not related_texts:
        return {}

    primary_combined = " ".join(primary_texts)
    paths = list(related_texts.keys())
    all_docs = [primary_combined] + [related_texts[p] for p in paths]

    vectorizer = TfidfVectorizer(
        sublinear_tf=True,
        stop_words="english",
    )
    tfidf_matrix = vectorizer.fit_transform(all_docs)

    similarities = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:]).flatten()
    return {paths[i]: float(similarities[i]) for i in range(len(paths))}


# ── Structural Boosters ──────────────────────────────────────


BOOST_FRONT_MATTER = 0.75    # Tier 0: author-curated declaration
BOOST_CROSS_REF = 0.50       # Tier 1: explicit authorial declaration
BOOST_DEPENDENCY = 0.50      # Tier 1: explicit authorial declaration
BOOST_FILENAME_PAIR = 0.15   # Tier 2: structural convention
BOOST_PARENT_REF = 0.10      # Tier 2: provenance marker


def _parse_links(text: str, spec_dir: str) -> set[str]:
    """Extract resolved file paths from markdown links in text."""
    link_re = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
    resolved: set[str] = set()
    for _text, link_path in link_re.findall(text):
        if link_path.startswith(("http://", "https://", "#")):
            continue
        link_path = link_path.split("#")[0]
        if not link_path:
            continue
        resolved.add(os.path.normpath(os.path.join(spec_dir, link_path)))
    return resolved


def _apply_structural_boosts(
    primary_spec_texts: dict[str, str],
    related_spec_texts: dict[str, str],
    base_scores: dict[str, float],
    project_root: str,
    fm_declared_paths: set[str],
) -> dict[str, dict]:
    """Apply structural boosters to base TF-IDF scores.

    Returns {path: {"score": float, "tfidf": float, "signals": list[str]}}
    with final scores and a record of which signals contributed.
    """
    results: dict[str, dict] = {}
    for path in related_spec_texts:
        results[path] = {
            "score": base_scores.get(path, 0.0),
            "tfidf": base_scores.get(path, 0.0),
            "signals": [],
        }

    # Front-matter boost (Tier 0)
    for path in related_spec_texts:
        norm_path = os.path.normpath(path)
        if norm_path in fm_declared_paths:
            results[path]["score"] += BOOST_FRONT_MATTER
            results[path]["signals"].append("front_matter")

    # Collect all links from primary specs (cross-references)
    all_primary_links: set[str] = set()
    dependency_links: set[str] = set()
    parent_links: set[str] = set()

    for spec_path, content in primary_spec_texts.items():
        spec_dir = os.path.dirname(os.path.join(project_root, spec_path))
        all_primary_links.update(_parse_links(content, spec_dir))

        # Parse dependency and parent headers specifically
        for line in content.splitlines()[:20]:  # Headers are near the top
            if line.startswith("> Depends on:") or line.startswith(">Depends on:"):
                dependency_links.update(_parse_links(line, spec_dir))
            elif line.startswith("> Parent RFC:") or line.startswith("> See ["):
                parent_links.update(_parse_links(line, spec_dir))

    # Link-based boosts (Tier 1 and 2)
    primary_stems = {os.path.splitext(os.path.basename(p))[0] for p in primary_spec_texts}
    for path in related_spec_texts:
        abs_path = os.path.normpath(os.path.join(project_root, path))

        if abs_path in all_primary_links:
            if abs_path in dependency_links:
                results[path]["score"] += BOOST_DEPENDENCY
                results[path]["signals"].append("dependency_header")
            elif abs_path in parent_links:
                results[path]["score"] += BOOST_PARENT_REF
                results[path]["signals"].append("parent_ref")
            else:
                results[path]["score"] += BOOST_CROSS_REF
                results[path]["signals"].append("cross_ref")

        # Filename pairing boost (same stem, sibling directory)
        related_stem = os.path.splitext(os.path.basename(path))[0]
        if related_stem in primary_stems:
            related_dir = os.path.dirname(path)
            primary_dirs = {os.path.dirname(p) for p in primary_spec_texts}
            if related_dir not in primary_dirs:
                results[path]["score"] += BOOST_FILENAME_PAIR
                results[path]["signals"].append("filename_pair")

    return results


# ── Budget-Constrained Assembly ──────────────────────────────


def _assemble_within_budget(
    scored_specs: dict[str, dict],
    related_spec_texts: dict[str, str],
    budget_tokens: int,
    threshold: float,
) -> tuple[list[str], list[dict]]:
    """Assemble related specs within token budget, ordered by relevance score.

    Whole specs only. If a spec exceeds the remaining budget, skip it and
    try the next (a smaller spec may still fit). No truncation.

    Returns:
        (parts, scoring_log) where parts is a list of markdown blocks and
        scoring_log records each spec's disposition with reason.
    """
    ranked = sorted(scored_specs.items(), key=lambda x: x[1]["score"], reverse=True)

    parts: list[str] = []
    total_tokens = 0
    scoring_log: list[dict] = []

    for path, info in ranked:
        entry = {
            "path": path,
            "score": round(info["score"], 4),
            "tfidf": round(info["tfidf"], 4),
            "signals": info["signals"],
        }

        if info["score"] < threshold:
            entry["disposition"] = "excluded"
            entry["reason"] = f"below threshold {threshold}"
            scoring_log.append(entry)
            continue

        content = related_spec_texts[path]
        signals_str = ", ".join(info["signals"]) if info["signals"] else "tfidf only"
        header = f"--- RELATED SPEC: {path} (score={info['score']:.2f}, {signals_str}) ---"
        block = f"{header}\n\n{content}"
        block_tokens = estimate_tokens_from_text(block)

        if total_tokens + block_tokens <= budget_tokens:
            parts.append(block)
            total_tokens += block_tokens
            entry["disposition"] = "included"
            entry["reason"] = ""
        else:
            entry["disposition"] = "excluded"
            entry["reason"] = (
                f"exceeds remaining budget "
                f"({budget_tokens - total_tokens} tokens left, spec needs {block_tokens})"
            )

        scoring_log.append(entry)

    return parts, scoring_log


# ── Public API ───────────────────────────────────────────────


class ScoringError(Exception):
    """Hard stop: scoring cannot produce reliable output."""
    def __init__(self, message: str, scoring_log: list[dict]):
        super().__init__(message)
        self.scoring_log = scoring_log


def score_and_assemble_specs(
    primary_spec_texts: dict[str, str],
    related_spec_texts: dict[str, str],
    project_root: str,
    budget_tokens: int = 15000,
    threshold: float = 0.05,
    candidate_cap: int = 50,
) -> tuple[str, list[dict]]:
    """Score related specs for relevance and assemble within budget.

    Seven-step pipeline (see Section 3 system diagram):
      1. Parse front-matter declarations from primary specs
      2. Hard stop #1: candidate cap
      3. Signal 1: TF-IDF content similarity
      4. Hard stops #2 (all below threshold), #3 (no differentiation)
      5. Signal 2: Structural boosters
      6. Hard stop #4: budget monopolized
      7. Assembly: Budget-constrained selection (whole specs only)

    Args:
        primary_spec_texts: {path: content} for the feature's own specs
        related_spec_texts: {path: content} for all other specs
        project_root: absolute path to project root (for resolving relative links)
        budget_tokens: maximum token budget for output
        threshold: minimum score for inclusion (default 0.05, deliberately low)
        candidate_cap: maximum candidate specs before hard stop (default 50)

    Returns:
        (assembled_markdown, scoring_log) where scoring_log is a list of
        dicts with path, score, tfidf, signals, disposition, and reason.

    Raises:
        ScoringError: hard stop condition detected with no front-matter
            declarations to narrow the candidate set. The exception carries
            a scoring_log for diagnostics (G2).
    """
    if not related_spec_texts:
        return "", []

    warnings: list[str] = []

    # Step 1: Parse front-matter declarations
    fm_declared_paths = _parse_front_matter(primary_spec_texts)

    # Step 2: Hard stop #1 — candidate cap
    candidate_count = len(related_spec_texts)
    if candidate_count > candidate_cap:
        if not fm_declared_paths:
            raise ScoringError(
                f"{candidate_count} related specs exceeds cap of {candidate_cap}. "
                f"Automatic scoring is unreliable at this scale. "
                f"Add `related:` front-matter to your primary spec or narrow `--specs-dir`.",
                scoring_log=[],
            )
        narrowed = {p: c for p, c in related_spec_texts.items()
                    if os.path.normpath(p) in fm_declared_paths}
        warnings.append(
            f"{candidate_count} specs exceeds cap of {candidate_cap}. "
            f"{len(narrowed)} front-matter declared specs included."
        )
        related_spec_texts = narrowed

    # Step 3: Signal 1 — TF-IDF content similarity
    primary_texts = list(primary_spec_texts.values())
    tfidf_scores = _compute_tfidf_scores(primary_texts, related_spec_texts)

    # Stale front-matter warnings
    for path in related_spec_texts:
        norm_path = os.path.normpath(path)
        if norm_path in fm_declared_paths and tfidf_scores.get(path, 0.0) < 0.01:
            warnings.append(
                f"Front-matter declared spec {path} has near-zero content similarity "
                f"(tfidf={tfidf_scores[path]:.4f}). The declaration may be stale, or the "
                f"specs may use different vocabulary for related concepts. "
                f"Included per author declaration. Verify front-matter is current."
            )

    # Step 4: Hard stops #2 and #3 (raw TF-IDF, before boosting)
    if tfidf_scores:
        max_tfidf = max(tfidf_scores.values())
        min_tfidf = min(tfidf_scores.values())
        tfidf_spread = max_tfidf - min_tfidf

        # Hard stop #2: all below threshold
        if max_tfidf < threshold:
            if not fm_declared_paths:
                raise ScoringError(
                    f"No related specs scored above threshold {threshold}. "
                    f"Max score: {max_tfidf:.4f}. "
                    f"Spec scoring cannot determine relevance for this input.",
                    scoring_log=[{
                        "path": p, "score": round(s, 4), "tfidf": round(s, 4),
                        "signals": [], "disposition": "excluded",
                        "reason": f"below threshold {threshold}",
                    } for p, s in tfidf_scores.items()],
                )
            narrowed = {p: c for p, c in related_spec_texts.items()
                        if os.path.normpath(p) in fm_declared_paths}
            warnings.append(
                f"All TF-IDF scores below threshold {threshold}. "
                f"{len(narrowed)} front-matter specs included."
            )
            related_spec_texts = narrowed
            tfidf_scores = {p: s for p, s in tfidf_scores.items() if p in narrowed}

        # Hard stop #3: no differentiation
        elif tfidf_spread < 0.05:
            if not fm_declared_paths:
                raise ScoringError(
                    f"Score spread is {tfidf_spread:.4f} (below minimum 0.05). "
                    f"TF-IDF cannot differentiate relevance. "
                    f"All specs appear equally (un)related.",
                    scoring_log=[{
                        "path": p, "score": round(s, 4), "tfidf": round(s, 4),
                        "signals": [], "disposition": "excluded",
                        "reason": f"spread {tfidf_spread:.4f} < 0.05",
                    } for p, s in tfidf_scores.items()],
                )
            narrowed = {p: c for p, c in related_spec_texts.items()
                        if os.path.normpath(p) in fm_declared_paths}
            warnings.append(
                f"TF-IDF can't differentiate (spread {tfidf_spread:.4f}). "
                f"{len(narrowed)} front-matter specs included."
            )
            related_spec_texts = narrowed
            tfidf_scores = {p: s for p, s in tfidf_scores.items() if p in narrowed}

    # Step 5: Signal 2 — Structural boosters
    scored = _apply_structural_boosts(
        primary_spec_texts, related_spec_texts, tfidf_scores, project_root,
        fm_declared_paths,
    )

    # Step 6: Hard stop #4 — budget monopolized
    for path, info in scored.items():
        if info["score"] >= threshold:
            content = related_spec_texts[path]
            spec_tokens = estimate_tokens_from_text(content)
            if spec_tokens > budget_tokens * 0.5:
                norm_path = os.path.normpath(path)
                pct = int(spec_tokens / budget_tokens * 100)
                if norm_path in fm_declared_paths:
                    warnings.append(
                        f"Front-matter declared spec {path} is {spec_tokens} tokens "
                        f"({pct}% of {budget_tokens} budget). "
                        f"Included per author declaration."
                    )
                else:
                    raise ScoringError(
                        f"Spec {path} is {spec_tokens} tokens "
                        f"({pct}% of {budget_tokens} budget). "
                        f"Single spec exceeds 50% cap.",
                        scoring_log=[{
                            "path": p, "score": round(i["score"], 4),
                            "tfidf": round(i["tfidf"], 4), "signals": i["signals"],
                            "disposition": "excluded" if p == path else "pending",
                            "reason": (f"{spec_tokens} tokens > 50% of {budget_tokens}"
                                       if p == path else ""),
                        } for p, i in scored.items()],
                    )

    # Step 7: Assembly — Budget-constrained selection (whole specs only)
    parts, scoring_log = _assemble_within_budget(
        scored, related_spec_texts, budget_tokens, threshold
    )

    # Emit warnings to stderr
    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)

    assembled = "\n\n".join(parts)
    return assembled, scoring_log
