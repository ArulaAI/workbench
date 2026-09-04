"""Repository Digest — Phase 5B: Changes History.

Computed entirely at read time (mirrors attach_effective_state's own
pattern in repository_digest.py) — never persisted into
repository-digest.json. This is what structurally prevents the
recursive-nesting problem: the current digest never contains a copy of
the previous one, and the previous-snapshot file
(.speed/context/repository-digest-previous.json) is a plain digest, not
a digest-plus-history. Only one snapshot is ever kept — see
build_repository_digest()'s snapshot-rotation step, right before its
existing atomic write, for the lifecycle rule (a digest is only ever
promoted to "previous" after it has already passed validate_digest()).

Comparison scope: this module only reads two already-loaded digest
dicts and derives a diff — it never touches the filesystem, never
rebuilds anything, and makes no network calls, matching the existing
read path's own documented constraint ("never rebuilds, walks the
repository, or invokes an agent provider" — repository_digest.py's
get_repository_digest()).

Fields intentionally excluded from comparison: `generated_at`,
`fingerprint`, and any `evidence[].line` are never used as a change
trigger (a route's line shifting because of an unrelated edit earlier
in the same file is noise, not a real change) — evidence is still
carried through on every added/removed/changed entry for context, just
never diffed itself. Environment variable *values* are structurally
absent from both digests already (Phase 4/5A never store them), so
there is nothing to compare or leak here either.
"""

from __future__ import annotations

from typing import Any, Callable, Hashable


def _snapshot_meta(digest: dict[str, Any]) -> dict[str, Any]:
    return {
        "generated_at": digest.get("generated_at"),
        "git_head": (digest.get("fingerprint") or {}).get("git_head"),
        "identity_name": (digest.get("identity") or {}).get("name"),
        "schema_version": digest.get("schema_version"),
    }


def _diff_list(
    section_key: str,
    section_label: str,
    before_items: list[dict[str, Any]] | None,
    after_items: list[dict[str, Any]] | None,
    key_fn: Callable[[dict[str, Any]], Hashable],
    title_fn: Callable[[dict[str, Any]], str],
    compare_fields: tuple[str, ...],
) -> dict[str, Any]:
    """Generic ADDED/REMOVED/CHANGED diff for a list of dicts, used for
    every list-shaped digest section (domains, relationships, routes,
    entities, CI workflows, runtimes, frameworks, config sources, env
    var names, secret indicators, sensitive configuration, auth
    indicators, security tooling, readiness).
    """
    if before_items is None or after_items is None:
        missing_in = "the previous digest" if before_items is None else "the current digest"
        return {
            "key": section_key, "label": section_label, "available": False,
            "reason": f"not present in {missing_in} — schema predates this section",
            "added": [], "removed": [], "changed": [],
        }

    before_by_key = {key_fn(i): i for i in before_items if isinstance(i, dict)}
    after_by_key = {key_fn(i): i for i in after_items if isinstance(i, dict)}

    added = [
        {"key": str(k), "title": title_fn(after_by_key[k]), "evidence": after_by_key[k].get("evidence", [])}
        for k in sorted(after_by_key.keys() - before_by_key.keys(), key=str)
    ]
    removed = [
        {"key": str(k), "title": title_fn(before_by_key[k]), "evidence": before_by_key[k].get("evidence", [])}
        for k in sorted(before_by_key.keys() - after_by_key.keys(), key=str)
    ]
    changed = []
    for k in sorted(before_by_key.keys() & after_by_key.keys(), key=str):
        b, a = before_by_key[k], after_by_key[k]
        field_diffs = [
            {"field": f, "before": b.get(f), "after": a.get(f)}
            for f in compare_fields
            if b.get(f) != a.get(f)
        ]
        if field_diffs:
            changed.append({
                "key": str(k), "title": title_fn(a), "fields": field_diffs,
                "evidence": a.get("evidence", []),
            })

    return {
        "key": section_key, "label": section_label, "available": True, "reason": None,
        "added": added, "removed": removed, "changed": changed,
    }


def _coerce_hashable(value: Any) -> Hashable:
    if isinstance(value, list):
        return tuple(sorted(_coerce_hashable(v) for v in value))
    if isinstance(value, dict):
        return tuple(sorted((k, _coerce_hashable(v)) for k, v in value.items()))
    return value


def _column_names(entity: dict[str, Any]) -> Hashable:
    return tuple(sorted(c.get("name", "") for c in entity.get("columns") or [] if isinstance(c, dict)))


def _relationship_targets(entity: dict[str, Any]) -> Hashable:
    return tuple(sorted(r.get("target_entity", "") for r in entity.get("relationships") or [] if isinstance(r, dict)))


def _job_names(workflow: dict[str, Any]) -> Hashable:
    return tuple(sorted(j.get("name", "") for j in workflow.get("jobs") or [] if isinstance(j, dict)))


def _domain_diff_keys(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> dict[int, Hashable]:
    """Diff identity per domain, keyed by Python object identity (safe
    here: `before`/`after` are the same lists — same dict objects, no
    copies — that _diff_domains immediately turns around and hands to
    _diff_list, which reads each key back from the very same objects).

    label alone remains the identity whenever it's already unique —
    preserving _SECTION_SPECS' measured stability property (72/86 label
    overlap vs. 18/86 for id, across two rebuilds of this repo with no
    real change) for every domain that ISN'T colliding, which is the
    overwhelming majority.

    Code-review regression: label is derived by TF-IDF plurality vote,
    not guaranteed unique — two structurally different clusters (e.g. a
    frontend "Models" cluster and an unrelated backend "Models" cluster)
    can independently land on the same label. Dict-comprehension keying
    by label alone then silently collapses them into one slot, which can
    both fabricate a phantom "changed" event (comparing two unrelated
    domains' attributes against each other) and hide a genuine deletion
    (the removed one's absence is masked by the surviving one sharing
    its key).

    Only actually-colliding labels get a refined key — each of their
    domains' own top representative_files entry (its most-central-
    symbol's file, itself deterministic per domain) — rather than
    switching every domain over to a composite key. This is deliberately
    NOT `lane`: lane is coarse (five possible values) and can
    legitimately change for the very same domain between rebuilds as its
    file mix shifts, which would turn a real "changed" event into fake
    churn — exactly the failure mode this fix must not reintroduce.
    representative_files doesn't have that problem: it reflects what the
    domain actually contains, not a derived classification of it.

    A label's collision status is decided per snapshot (before and after
    separately), then the union of both is used for every domain sharing
    that label on EITHER side — never a single count over before+after
    combined, which would flag every ordinary persisting domain as
    "colliding" against its own other-snapshot self (the same label
    naturally appears at least twice — once per snapshot — for a domain
    that isn't added or removed at all). And never a per-snapshot-only
    decision either, or a domain whose one-time same-label sibling gets
    deleted would flip from a disambiguated key to a plain one purely
    because the sibling is gone, misreporting real "no change" as a
    fabricated remove+add.
    """
    from collections import Counter

    before_counts = Counter(d.get("label") for d in before)
    after_counts = Counter(d.get("label") for d in after)
    colliding_labels = {lbl for lbl, n in before_counts.items() if n > 1} | {lbl for lbl, n in after_counts.items() if n > 1}

    keys: dict[int, Hashable] = {}
    for d in before + after:
        label = d.get("label")
        if label not in colliding_labels:
            keys[id(d)] = label
            continue
        rep_files = d.get("representative_files") or []
        keys[id(d)] = (label, rep_files[0] if rep_files else d.get("id"))
    return keys


def _diff_domains(current: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    before_domains = _get_path(previous, ("domains",))
    after_domains = _get_path(current, ("domains",))
    if before_domains is None or after_domains is None:
        missing_in = "the previous digest" if before_domains is None else "the current digest"
        return {
            "key": "domains", "label": "Domains", "available": False,
            "reason": f"not present in {missing_in} — schema predates this section",
            "added": [], "removed": [], "changed": [],
        }

    before_valid = [d for d in before_domains if isinstance(d, dict)]
    after_valid = [d for d in after_domains if isinstance(d, dict)]
    keys = _domain_diff_keys(before_valid, after_valid)

    return _diff_list(
        "domains", "Domains", before_valid, after_valid,
        lambda d: keys[id(d)],
        lambda d: d.get("label", d.get("id", "")),
        ("lane", "file_count", "symbol_count"),
    )


def _diff_relationships(current: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    """Relationship endpoints (`from`/`to`) are cluster IDs, which carry
    the same unstable numeric suffix as domain IDs (see _SECTION_SPECS'
    comment on domains) — resolved to each side's own domain *label*
    before diffing, for the same accuracy reason.
    """
    before_rels = _get_path(previous, ("relationships",))
    after_rels = _get_path(current, ("relationships",))
    if before_rels is None or after_rels is None:
        missing_in = "the previous digest" if before_rels is None else "the current digest"
        return {
            "key": "relationships", "label": "Relationships", "available": False,
            "reason": f"not present in {missing_in} — schema predates this section",
            "added": [], "removed": [], "changed": [],
        }

    before_id_to_label = {d.get("id"): d.get("label", d.get("id", "")) for d in (_get_path(previous, ("domains",)) or [])}
    after_id_to_label = {d.get("id"): d.get("label", d.get("id", "")) for d in (_get_path(current, ("domains",)) or [])}

    def _remap(rels: list[dict[str, Any]], id_to_label: dict[Any, str]) -> list[dict[str, Any]]:
        remapped = []
        for r in rels:
            # A non-dict entry (a hand-edited or older-schema previous
            # snapshot has no guarantee here) would crash dict(r) below,
            # before _diff_list's own isinstance filter ever runs — same
            # member-type safety the rest of this module already applies.
            if not isinstance(r, dict):
                continue
            r2 = dict(r)
            r2["from"] = id_to_label.get(r.get("from"), r.get("from"))
            r2["to"] = id_to_label.get(r.get("to"), r.get("to"))
            remapped.append(r2)
        return remapped

    return _diff_list(
        "relationships", "Relationships",
        _remap(before_rels, before_id_to_label), _remap(after_rels, after_id_to_label),
        lambda r: (r.get("from"), r.get("to")), lambda r: f"{r.get('from')} → {r.get('to')}",
        ("weight", "evidence_type"),
    )


def _diff_coverage(current: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    before = previous.get("coverage_stats")
    after = current.get("coverage_stats")
    # Code-review regression: .get(f) below assumed a dict without
    # checking — a non-dict coverage_stats (a hand-edited/legacy/
    # corrupted snapshot: "unknown", a bare number, a list, ...) raised
    # AttributeError here, and the caller's blanket except Exception one
    # level out (attach_changes_history) then discarded the *entire*
    # Changes History result — every other section's real diff, not
    # just this one — to recover from it. None (genuinely absent, the
    # pre-Phase-2 backward-compat case) and any other non-dict value are
    # both treated the same way: "not present," never a crash.
    if not isinstance(before, dict) or not isinstance(after, dict):
        missing_in = "the previous digest" if not isinstance(before, dict) else "the current digest"
        return {
            "key": "coverage", "label": "Coverage", "available": False,
            "reason": f"not present in {missing_in}", "added": [], "removed": [], "changed": [],
        }
    fields = ("source_files_total", "source_files_parsed", "parse_coverage_pct")
    field_diffs = [{"field": f, "before": before.get(f), "after": after.get(f)} for f in fields if before.get(f) != after.get(f)]
    changed = [{"key": "coverage", "title": "Discovery coverage", "fields": field_diffs, "evidence": []}] if field_diffs else []
    return {"key": "coverage", "label": "Coverage", "available": True, "reason": None, "added": [], "removed": [], "changed": changed}


_SECTION_SPECS: tuple[tuple[str, str, tuple[str, ...], Callable, Callable, tuple[str, ...]], ...] = (
    # Domains are NOT here — they need collision-aware keying (two
    # domains can share a label) that this generic per-item key_fn
    # signature can't express on its own. See _diff_domains/
    # _domain_diff_keys, called separately in derive_changes_history.
    ("routes", "API routes", ("api_data", "routes"), lambda r: (r.get("method"), r.get("path"), r.get("file")), lambda r: f"{r.get('method')} {r.get('path')}", ("handler", "framework")),
    ("entities", "Entities", ("api_data", "entities"), lambda e: (e.get("name"), e.get("file")), lambda e: e.get("name", ""), ()),  # columns/relationships compared separately below
    ("cicd_workflows", "CI/CD workflows", ("cicd", "workflows"), lambda w: w.get("config_file"), lambda w: w.get("name", w.get("config_file", "")), ("name",)),  # triggers/jobs compared separately below
    ("runtimes", "Runtimes", ("runtime_config", "runtimes"), lambda r: (r.get("language"), r.get("source_file")), lambda r: r.get("language", ""), ("version",)),
    ("frameworks", "Frameworks", ("runtime_config", "frameworks"), lambda f: (f.get("name"), f.get("source_file")), lambda f: f.get("name", ""), ("version",)),
    ("config_sources", "Configuration sources", ("runtime_config", "config_sources"), lambda c: c.get("file"), lambda c: c.get("file", ""), ()),
    ("environment_variables", "Environment variable names", ("runtime_config", "environment_variables"), lambda e: (e.get("name"), e.get("source_file")), lambda e: e.get("name", ""), ("looks_sensitive",)),
    ("secret_indicators", "Secret indicators", ("security", "secret_indicators"), lambda i: (i.get("category"), i.get("pattern_type"), i.get("name"), i.get("file")), lambda i: i.get("name") or i.get("pattern_type") or i.get("category", ""), ()),
    ("sensitive_configuration", "Sensitive configuration", ("security", "sensitive_configuration"), lambda c: (c.get("category"), c.get("file")), lambda c: c.get("title", ""), ("severity",)),
    ("authentication_indicators", "Authentication indicators", ("security", "authentication_indicators"), lambda a: (a.get("type"), a.get("name"), a.get("file")), lambda a: a.get("name", ""), ()),
    ("security_tooling", "Security tooling detected", ("security", "security_tooling_detected"), lambda t: t.get("name"), lambda t: t.get("name", ""), ()),
    ("readiness", "Discovery readiness", ("readiness",), lambda r: r.get("capability"), lambda r: r.get("capability", ""), ("status",)),
)


def _merge_field_diffs(
    changed: list[dict[str, Any]], key: str, title: str,
    field_diffs: list[dict[str, Any]], evidence: list[dict[str, Any]],
) -> None:
    """Add field_diffs to the entry for `key` in a section's 'changed'
    list, merging into an existing entry rather than skipping — the
    generic _diff_list pass above (compare_fields) may have already
    created an entry for this same key from an unrelated field, and a
    'key already present, skip' check would silently discard these
    nested-field diffs instead of surfacing both. Concretely: a CI
    workflow renamed and given a new job in the same rebuild must show
    both changes, not just whichever pass reaches it first.
    """
    if not field_diffs:
        return
    existing = next((c for c in changed if c["key"] == key), None)
    if existing is not None:
        existing["fields"].extend(field_diffs)
    else:
        changed.append({"key": key, "title": title, "fields": field_diffs, "evidence": evidence})


def _get_path(digest: dict[str, Any], path: tuple[str, ...]) -> list[dict[str, Any]] | None:
    node: Any = digest
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node if isinstance(node, list) else None


def derive_changes_history(current: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    current_meta = _snapshot_meta(current)

    if previous is None:
        return {
            "status": "first_run",
            "previous_snapshot": None,
            "current_snapshot": current_meta,
            "summary": [],
            "sections": [],
            "warnings": [],
        }

    previous_meta = _snapshot_meta(previous)
    warnings: list[str] = []
    if current_meta["identity_name"] and previous_meta["identity_name"] and current_meta["identity_name"] != previous_meta["identity_name"]:
        warnings.append(
            f"repository identity changed between snapshots ({previous_meta['identity_name']!r} -> {current_meta['identity_name']!r}) — comparison may not be meaningful"
        )
    if not current_meta["git_head"] or not previous_meta["git_head"]:
        warnings.append("git revision unavailable for one or both snapshots — comparison is based on digest content only, not a commit range")

    sections = [_diff_domains(current, previous)] + [
        _diff_list(key, label, _get_path(previous, path), _get_path(current, path), key_fn, title_fn, compare_fields)
        for key, label, path, key_fn, title_fn, compare_fields in _SECTION_SPECS
    ]

    # Entities: columns/relationships are nested lists, compared as a
    # normalized name-only signature rather than via the generic
    # compare_fields (which only diffs scalar values).
    entities_section = next(s for s in sections if s["key"] == "entities")
    if entities_section["available"]:
        before_entities = {(e.get("name"), e.get("file")): e for e in (_get_path(previous, ("api_data", "entities")) or [])}
        after_entities = {(e.get("name"), e.get("file")): e for e in (_get_path(current, ("api_data", "entities")) or [])}
        for k in sorted(before_entities.keys() & after_entities.keys(), key=str):
            b, a = before_entities[k], after_entities[k]
            field_diffs = []
            if _column_names(b) != _column_names(a):
                field_diffs.append({"field": "columns", "before": list(_column_names(b)), "after": list(_column_names(a))})
            if _relationship_targets(b) != _relationship_targets(a):
                field_diffs.append({"field": "relationships", "before": list(_relationship_targets(b)), "after": list(_relationship_targets(a))})
            _merge_field_diffs(entities_section["changed"], str(k), a.get("name", ""), field_diffs, a.get("evidence", []))

    # CI workflows: triggers/jobs are nested, compared as normalized
    # signatures the same way.
    cicd_section = next(s for s in sections if s["key"] == "cicd_workflows")
    if cicd_section["available"]:
        before_wf = {w.get("config_file"): w for w in (_get_path(previous, ("cicd", "workflows")) or [])}
        after_wf = {w.get("config_file"): w for w in (_get_path(current, ("cicd", "workflows")) or [])}
        for k in sorted(before_wf.keys() & after_wf.keys(), key=str):
            b, a = before_wf[k], after_wf[k]
            field_diffs = []
            if _coerce_hashable(b.get("triggers")) != _coerce_hashable(a.get("triggers")):
                field_diffs.append({"field": "triggers", "before": b.get("triggers"), "after": a.get("triggers")})
            if _job_names(b) != _job_names(a):
                field_diffs.append({"field": "jobs", "before": list(_job_names(b)), "after": list(_job_names(a))})
            _merge_field_diffs(cicd_section["changed"], str(k), a.get("name", k), field_diffs, a.get("evidence", []))

    sections.append(_diff_relationships(current, previous))
    sections.append(_diff_coverage(current, previous))

    summary = _build_summary(sections)

    return {
        "status": "compared",
        "previous_snapshot": previous_meta,
        "current_snapshot": current_meta,
        "summary": summary,
        "sections": sections,
        "warnings": warnings,
    }


# Section labels whose naive "strip a trailing s" singular form is wrong
# — either a genuine irregular plural ("Entities" -> "entitie" is not a
# word; it's "entity") or a label that already reads as singular/
# uncountable and must not be touched at all ("Discovery readiness"
# happens to end in "s" but "discovery readines" is not the word either).
# Every other _SECTION_SPECS label (Domains, Runtimes, Frameworks, ...)
# is a regular plural the strip-trailing-s fallback already handles
# correctly, so this stays a short exception list, not a general
# pluralization engine.
_IRREGULAR_SINGULAR: dict[str, str] = {
    "entities": "entity",
    "discovery readiness": "discovery readiness",
}


def _singularize(label: str) -> str:
    lowered = label.lower()
    if lowered in _IRREGULAR_SINGULAR:
        return _IRREGULAR_SINGULAR[lowered]
    return lowered[:-1] if lowered.endswith("s") else lowered


def _build_summary(sections: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for s in sections:
        if not s["available"]:
            continue
        added, removed, changed = len(s["added"]), len(s["removed"]), len(s["changed"])
        if added:
            lines.append(f"+{added} {s['label'].lower()}" if added != 1 else f"+1 {_singularize(s['label'])}")
        if removed:
            lines.append(f"-{removed} {s['label'].lower()}" if removed != 1 else f"-1 {_singularize(s['label'])}")
        if changed:
            if s["key"] == "runtimes" and len(s["changed"]) == 1:
                c = s["changed"][0]
                version_diff = next((f for f in c["fields"] if f["field"] == "version"), None)
                if version_diff:
                    lines.append(f"Runtime ({c['title']}) changed from {version_diff['before']} to {version_diff['after']}")
                    continue
            lines.append(f"{changed} {s['label'].lower()} changed")
    return lines
