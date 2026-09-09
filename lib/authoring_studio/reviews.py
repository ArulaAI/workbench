"""Publication checks and author acknowledgements, bound to an exact snapshot."""
import re


PLACEHOLDER = re.compile(r"\b(?:TBD|TODO|FIXME)\b", re.IGNORECASE)
UNRESOLVED = re.compile(
    r"\b(?:TBD|TODO|FIXME|unknown|unassigned|unspecified|undecided|unconfirmed)\b"
    r"|\bnot (?:yet )?(?:defined|specified|assigned|decided|confirmed|provided)\b"
    r"|\bno (?:target|owner|baseline|measurement method) (?:is )?(?:defined|specified|assigned|provided)\b"
    r"|\b(?:left open|to be (?:determined|confirmed|defined|assigned))\b", re.IGNORECASE)


def section_findings(section, pattern=PLACEHOLDER):
    fields = [("Section text", section["body"], f"section-{section['id']}")]
    for item in section["items"]:
        fields += [(f"{item['id']} · {label}", item[key], f"item-{item['id']}")
                   for key, label in (("statement", "Statement"), ("verification", "Verification / outcome"))]
    findings = []
    for location, text, anchor in fields:
        matches = list(pattern.finditer(text))
        if matches:
            # Quote the actual field with enough surrounding text to locate the issue.
            start, end = max(0, matches[0].start() - 72), min(len(text), matches[0].end() + 140)
            findings.append({"location": location, "anchor": anchor,
                             "excerpt": ("…" if start else "") + text[start:end] + ("…" if end < len(text) else "")})
    return findings


def saved_reviews(document, version_id):
    """Published review evidence is frozen even if a later draft gets new reviews."""
    publication = next((p for p in reversed(document.get("publications", [])) if p["version_id"] == version_id), None)
    if publication:
        return publication.get("reviews", [])
    latest = {}
    for record in document.get("review_history", []):
        if record["version_id"] == version_id:
            latest[record["group"]] = record
    return [record for record in latest.values() if record["disposition"] != "revoked"]


def publication_review(state, snapshot):
    if not snapshot:
        return []
    definitions = ([('success', 'Success', ['success'])] if snapshot['kind'] == 'prd' else [])
    definitions += [('open_questions', 'Open questions', ['risks'] if snapshot['kind'] == 'prd' else ['decisions'])]
    accepted = {record["group"]: record for record in saved_reviews(state["documents"][snapshot["kind"]], snapshot["id"])}
    legacy = any(p['version_id'] == snapshot['id'] and 'reviews' not in p
                 for p in state['documents'][snapshot['kind']].get('publications', []))
    groups = []
    for key, title, section_ids in definitions:
        sections = [s for s in snapshot['sections'] if s['id'] in section_ids]
        findings = [finding for s in sections for finding in section_findings(s, UNRESOLVED)]
        questions = snapshot['questions'] if key == 'open_questions' else []
        findings += [{"location": q['id'], "anchor": f"question-{q['id']}", "excerpt": q['question']} for q in questions]
        groups.append({"id": key, "title": title, "sections": [{"id": s['id'], "title": s['title']} for s in sections],
                       "findings": findings, "requires_deferral": bool(findings), "acknowledgement": accepted.get(key),
                       "legacy_published": legacy})
    return groups
