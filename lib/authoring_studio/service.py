"""Authoring commands. All mutations, including worker completion, are atomic."""
from __future__ import annotations

import copy
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .models import Command, CreateFeature, Generation, PREFIXES, RFC_MODULES, TEMPLATES
from .store import Store


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def uid() -> str:
    return uuid4().hex


class StudioError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class Studio:
    def __init__(self, project_root: Path, db_path: Path | None = None):
        self.root = project_root.resolve()
        self.store = Store(db_path or self.root / ".speed/studio/studio.sqlite3")

    def _read(self, conn, feature_id):
        state = self.store.read(conn, feature_id)
        if state is None:
            raise StudioError("Feature not found", 404)
        return state

    def version(self, feature_id, version_id):
        with self.store.transaction() as conn:
            result = self.store.load_snapshot(conn, version_id)
            if not result or result["feature_id"] != feature_id:
                raise StudioError("Version not found", 404)
            return result

    def _head(self, conn, state, kind):
        head = state["documents"][kind]["head"]
        return self.store.load_snapshot(conn, head) if head else None

    def list(self):
        with self.store.transaction() as conn:
            states = [self._view(conn, self.store.read(conn, row[0]), compact=True)
                      for row in conn.execute("SELECT id FROM features").fetchall()]
            return sorted(states, key=lambda s: s["updated_at"], reverse=True)

    def get(self, feature_id):
        with self.store.transaction() as conn:
            return self._view(conn, self._read(conn, feature_id))

    def create(self, request: CreateFeature):
        with self.store.transaction() as conn:
            for row in conn.execute("SELECT state FROM features").fetchall():
                import json
                old = json.loads(row[0])
                if old.get("create_request_id") == request.request_id:
                    return self._view(conn, old)
            state = {
                "id": uid(), "title": request.title.strip(), "brief": request.brief.strip(),
                "context": request.context.strip(), "revision": 0, "created_at": now(), "updated_at": now(),
                "create_request_id": request.request_id, "documents": {
                    k: {"head": None, "published": None, "versions": [], "publications": []} for k in TEMPLATES},
                "messages": [], "comments": [], "operations": [], "requests": [], "counters": {},
            }
            self._enqueue(state, "prd", "generate", request.brief.strip(), request.request_id, {})
            self._save(conn, state)
            return self._view(conn, state)

    def _save(self, conn, state):
        state["revision"] += 1
        state["updated_at"] = now()
        self.store.save(conn, state)

    @staticmethod
    def _active(state):
        return next((o for o in state["operations"] if o["status"] in ("queued", "running")), None)

    def _pins(self, conn, state, kind):
        if kind == "prd":
            return {}
        prd = state["documents"]["prd"]["published"]
        if not prd:
            raise StudioError("Publish a PRD snapshot before generating Design or RFC.")
        pins = {"prd": prd}
        design = state["documents"]["design"]
        if kind == "rfc" and design["head"]:
            if not design["published"]:
                raise StudioError("Publish the Design draft before using it in the RFC.")
            pinned_design = self.store.load_snapshot(conn, design["published"])
            if self._stale(state, pinned_design):
                raise StudioError("Reconcile and publish Design against the latest PRD before generating RFC.")
            pins["design"] = design["published"]
        return pins

    @staticmethod
    def _stale(state, snapshot):
        if not snapshot:
            return []
        changes = [kind for kind, version in snapshot["pins"].items()
                   if state["documents"][kind]["published"] != version]
        if snapshot["kind"] == "rfc" and "design" not in snapshot["pins"] and state["documents"]["design"]["published"]:
            changes.append("design")
        return changes

    def _blockers(self, state, snapshot):
        if not snapshot:
            return ["Generate a draft first."]
        blocks = [q["question"] for q in snapshot["questions"] if q["blocking"]]
        if self._stale(state, snapshot):
            blocks.append("Reconcile this document with the latest published upstream versions.")
        for section in snapshot["sections"]:
            if not section["body"].strip() and not section["items"]:
                blocks.append(f"Complete {section['title']}.")
            if section.get("needs_review"):
                blocks.append(f"Review protected section after upstream change: {section['title']}.")
            if section.get("unverified_source_ids"):
                blocks.append(f"Verify unavailable evidence references in {section['title']}: " + ", ".join(section["unverified_source_ids"]))
            if re.search(r"\b(?:TBD|TODO|FIXME)\b", section["body"] + " " + " ".join(i["statement"] + " " + i["verification"] for i in section["items"])):
                blocks.append(f"Replace unfinished placeholders in {section['title']} with a decision or an explicit open question.")
        blocks.extend(f"Resolve blocking comment: {c['text']}" for c in state["comments"]
                      if c["kind"] == snapshot["kind"] and c["blocking"] and c["status"] in ("open", "addressed"))
        blocks.extend(f"Decide RFC coverage: {c['module']} ({c['rationale']})"
                      for c in snapshot["coverage"] if snapshot["kind"] == "rfc" and c["status"] == "unresolved")
        if snapshot["kind"] == "prd":
            for section in snapshot["sections"]:
                if section["id"] in PREFIXES and not section["items"]:
                    blocks.append(f"Add at least one structured row to {section['title']}.")
        return blocks

    def _view(self, conn, state, compact=False):
        view = copy.deepcopy(state)
        for kind, doc in view["documents"].items():
            snapshot = self._head(conn, state, kind)
            doc["stale"] = self._stale(state, snapshot)
            doc["blockers"] = self._blockers(state, snapshot)
            if not compact:
                doc["snapshot"] = snapshot
        for comment in view["comments"]:
            snapshot = self._head(conn, state, comment["kind"])
            section = next((s for s in (snapshot or {}).get("sections", []) if s["id"] == comment["section_id"]), None)
            comment["outdated"] = bool(comment["quote"] and (not section or comment["quote"] not in section["body"]))
        if compact:
            for key in ("messages", "comments", "operations", "context", "requests", "counters"):
                view.pop(key, None)
        return view

    def _enqueue(self, state, kind, action, text, request_id, pins, section_id=None, comment_id=None):
        operation = {"id": uid(), "request_id": request_id, "kind": kind, "action": action, "text": text,
                     "section_id": section_id, "comment_id": comment_id, "pins": pins,
                     "base_version": state["documents"][kind]["head"], "status": "queued", "created_at": now(),
                     "error": None, "version_id": None}
        state["operations"].append(operation)
        state["messages"].append({"id": uid(), "role": "user", "kind": kind, "text": text,
                                  "section_id": section_id, "operation_id": operation["id"], "created_at": now()})
        return operation

    def command(self, feature_id, command: Command):
        with self.store.transaction() as conn:
            state = self._read(conn, feature_id)
            if command.request_id in state["requests"] or any(o["request_id"] == command.request_id for o in state["operations"]):
                return self._view(conn, state)
            if command.expected_revision != state["revision"]:
                raise StudioError("This workspace changed. The latest version has been loaded; review it and try again.", 409)
            active = self._active(state)
            if active and command.action != "cancel":
                raise StudioError("A revision is in progress. Wait for it or cancel it before making another change.", 409)
            kind, action = command.kind, command.action
            doc = state["documents"][kind]
            head = self._head(conn, state, kind)
            section = next((s for s in (head or {}).get("sections", []) if s["id"] == command.section_id), None)
            if command.section_id and not section and action != "comment":
                raise StudioError("Section not found.")

            if action in ("generate", "revise", "reconcile", "retry"):
                text, scoped, comment_id = command.text.strip(), command.section_id, command.comment_id
                actual_action = action
                if action == "generate" and head:
                    raise StudioError("A draft already exists. Use a revision request.")
                if action in ("revise", "reconcile") and not head:
                    raise StudioError("Generate a draft first.")
                if action == "retry":
                    failed = next((o for o in reversed(state["operations"]) if o["kind"] == kind and o["status"] in ("failed", "interrupted", "cancelled")), None)
                    if not failed:
                        raise StudioError("There is no failed request to retry.")
                    text, scoped, comment_id, actual_action = failed["text"], failed["section_id"], failed["comment_id"], failed["action"]
                if comment_id:
                    comment = self._comment(state, comment_id, kind)
                    if comment["status"] not in ("open", "addressed"):
                        raise StudioError("Reopen this comment before addressing it.")
                    scoped = comment["section_id"]
                    if comment["quote"] and comment["quote"] not in next(s for s in head["sections"] if s["id"] == scoped)["body"]:
                        raise StudioError("The quoted text changed. Review the comment and use a new section request.")
                    text = f"Address this reviewer comment in its section: {comment['text']}\nQuoted text: {comment['quote']}"
                if action == "generate":
                    text = text or f"Generate a {kind.upper()} using the published upstream documents."
                if action == "reconcile":
                    text = "Reconcile this document with the latest published upstream versions. Preserve unaffected decisions and existing IDs. Explain what changed."
                if not text:
                    raise StudioError("Describe the change you want.")
                pins = self._pins(conn, state, kind) if actual_action in ("generate", "reconcile") else (head or {}).get("pins", {})
                self._enqueue(state, kind, actual_action, text, command.request_id, pins, scoped, comment_id)
            elif action == "cancel":
                if not active:
                    raise StudioError("No revision is running.")
                active["status"] = "cancelled"
                active["error"] = "Cancelled by author. The saved request remains in the conversation."
            elif action == "publish":
                if not head or command.version_id != head["id"]:
                    raise StudioError("Only the exact current revision can be published.", 409)
                blockers = self._blockers(state, head)
                if blockers:
                    raise StudioError("Publication needs attention: " + " ".join(blockers))
                doc["published"] = head["id"]
                doc["publications"].append({"version_id": head["id"], "created_at": now()})
            elif action in ("edit", "review_section"):
                if not section:
                    raise StudioError("Choose a section to edit.")
                if command.version_id != head["id"]:
                    raise StudioError("This section was opened from an older version. Review the latest section before saving your edit.", 409)
                candidate = copy.deepcopy(head)
                target = next(s for s in candidate["sections"] if s["id"] == command.section_id)
                if action == "edit":
                    target["body"] = command.text
                    if command.items is not None:
                        target["items"] = [i.model_dump() for i in command.items]
                        self._assign_ids(state, head, candidate)
                    target["protected"] = True
                    self._validate_refs(conn, candidate)
                target["needs_review"] = False
                self._snapshot(conn, state, kind, candidate, "author", f"{'Reviewed' if action == 'review_section' else 'Edited'} {section['title']}")
            elif action == "restore":
                original = self.store.load_snapshot(conn, command.version_id)
                if not original or original["feature_id"] != feature_id or original["kind"] != kind:
                    raise StudioError("Version not found.", 404)
                self._snapshot(conn, state, kind, copy.deepcopy(original), "author", f"Restored v{original['number']} as a new revision")
            elif action == "comment":
                original = self.store.load_snapshot(conn, command.version_id)
                if not original or original["feature_id"] != feature_id or original["kind"] != kind:
                    raise StudioError("Comment source version not found.")
                target = next((s for s in original["sections"] if s["id"] == command.section_id), None)
                if not target or not command.text.strip():
                    raise StudioError("Choose a section and enter a comment.")
                if command.quote and command.quote not in target["body"]:
                    raise StudioError("The quotation does not occur in this section version.")
                state["comments"].append({"id": uid(), "kind": kind, "section_id": command.section_id,
                    "version_id": command.version_id, "quote": command.quote, "text": command.text.strip(),
                    "blocking": command.blocking, "status": "open", "created_at": now(), "addressed_version": None,
                    "dispositions": []})
            elif action in ("resolve", "dismiss", "reopen"):
                comment = self._comment(state, command.comment_id, kind)
                if action == "dismiss" and not command.text.strip():
                    raise StudioError("Add a reason for dismissing the comment.")
                comment["status"] = {"resolve": "resolved", "dismiss": "dismissed", "reopen": "open"}[action]
                comment["dispositions"].append({"status": comment["status"], "reason": command.text.strip(), "created_at": now()})
            state["requests"].append(command.request_id)
            self._save(conn, state)
            return self._view(conn, state)

    @staticmethod
    def _comment(state, comment_id, kind):
        comment = next((c for c in state["comments"] if c["id"] == comment_id and c["kind"] == kind), None)
        if not comment:
            raise StudioError("Comment not found.", 404)
        return comment

    def _assign_ids(self, state, head, candidate):
        existing = {i["id"]: s["id"] for s in (head or {}).get("sections", []) for i in s["items"]}
        remap, seen = {}, set()
        for section in candidate["sections"]:
            for item in section["items"]:
                item_id = item["id"]
                if item_id in seen:
                    raise StudioError(f"Duplicate entity ID: {item_id}")
                seen.add(item_id)
                local_first_draft_id = head is None and (candidate["kind"] == "prd" or not re.fullmatch(r"(?:US|REQ|GR|SM)-\d+", item_id))
                if item_id.startswith("new-") or local_first_draft_id:
                    prefix = PREFIXES.get(section["id"], "D" if candidate["kind"] == "design" else "DEC")
                    counter_key = f"{candidate['kind']}:{prefix}"
                    state["counters"][counter_key] = state["counters"].get(counter_key, 0) + 1
                    remap[item_id] = f"{prefix}-{state['counters'][counter_key]}"
                    item["id"] = remap[item_id]
                elif existing.get(item_id) != section["id"]:
                    raise StudioError(f"Unknown or moved entity ID: {item_id}. Use new-* for additions.")
        for section in candidate["sections"]:
            for item in section["items"]:
                item["references"] = [remap.get(ref, ref) for ref in item["references"]]
            # Resolve model-local references after the application allocates stable IDs.
            for old, new in sorted(remap.items(), key=lambda pair: -len(pair[0])):
                section["body"] = re.sub(r"(?<![\w-])" + re.escape(old) + r"(?![\w-])", new, section["body"])

        def replace(text):
            for old, new in sorted(remap.items(), key=lambda pair: -len(pair[0])):
                text = re.sub(r"(?<![\w-])" + re.escape(old) + r"(?![\w-])", new, text)
            return text
        candidate["assumptions"] = [replace(a) for a in candidate["assumptions"]]
        for section in candidate["sections"]:
            for item in section["items"]:
                item["statement"], item["verification"] = replace(item["statement"]), replace(item["verification"])
        for question in candidate["questions"]:
            question["question"], question["why"] = replace(question["question"]), replace(question["why"])
        for assessment in candidate["coverage"]:
            assessment["rationale"] = replace(assessment["rationale"])
        if "applied_summary" in candidate:
            candidate["applied_summary"] = replace(candidate["applied_summary"])

    def _snapshot(self, conn, state, kind, candidate, author, summary, operation_id=None):
        doc = state["documents"][kind]
        candidate.update({"id": uid(), "feature_id": state["id"], "kind": kind,
                          "number": len(doc["versions"]) + 1, "created_at": now(),
                          "parent_id": doc["head"], "author": author, "summary": summary,
                          "operation_id": operation_id})
        self.store.snapshot(conn, candidate)
        doc["head"] = candidate["id"]
        doc["versions"].append({key: candidate[key] for key in ("id", "number", "created_at", "author", "summary", "pins")})
        return candidate

    def recover(self):
        """Run once on startup. One API process owns this prototype's worker queue."""
        with self.store.transaction() as conn:
            for row in conn.execute("SELECT id FROM features").fetchall():
                state = self._read(conn, row[0])
                active = self._active(state)
                if active:
                    active.update(status="interrupted", error="The server restarted. Your request is saved. Retry to continue.")
                    self._save(conn, state)

    def run(self, feature_id, operation_id, generator):
        """Claim, generate outside the DB transaction, then atomically apply if still current."""
        with self.store.transaction() as conn:
            state = self._read(conn, feature_id)
            operation = next((o for o in state["operations"] if o["id"] == operation_id), None)
            if not operation or operation["status"] != "queued":
                return
            operation["status"] = "running"
            self._save(conn, state)
            head = self._head(conn, state, operation["kind"])
            upstream = {k: self.store.load_snapshot(conn, v) for k, v in operation["pins"].items()}
        try:
            generated, sources, model = generator(copy.deepcopy(state), copy.deepcopy(operation), head, upstream)
            generated = Generation.model_validate(generated)
            with self.store.transaction() as conn:
                current = self._read(conn, feature_id)
                active = next(o for o in current["operations"] if o["id"] == operation_id)
                if active["status"] != "running":
                    return
                if current["documents"][operation["kind"]]["head"] != operation["base_version"]:
                    raise StudioError("The base version changed during generation. Retry against the current document.")
                candidate = self._candidate(conn, current, operation, head, generated, sources, model)
                applied_summary = candidate.pop("applied_summary")
                snap = self._snapshot(conn, current, operation["kind"], candidate, "assistant", applied_summary, operation_id)
                active.update(status="completed", version_id=snap["id"])
                if operation["comment_id"]:
                    comment = self._comment(current, operation["comment_id"], operation["kind"])
                    comment.update(status="addressed", addressed_version=snap["id"])
                current["messages"].append({"id": uid(), "role": "assistant", "kind": operation["kind"],
                    "text": applied_summary, "section_id": operation["section_id"], "operation_id": operation_id,
                    "version_id": snap["id"], "created_at": now()})
                self._save(conn, current)
        except Exception as error:
            detail = "The model did not finish in time. Your request and current document are saved. Retry to continue." if isinstance(error, (subprocess.TimeoutExpired, TimeoutError)) else (str(error)[:800] or type(error).__name__)
            with self.store.transaction() as conn:
                state = self._read(conn, feature_id)
                operation = next(o for o in state["operations"] if o["id"] == operation_id)
                if operation["status"] == "running":
                    operation.update(status="failed", error=detail)
                    self._save(conn, state)

    def _candidate(self, conn, state, operation, head, generated, sources, model):
        kind = operation["kind"]
        titles = dict(TEMPLATES[kind])
        patches = {s.id: s.model_dump() for s in generated.sections}
        if len(patches) != len(generated.sections) or set(patches) - set(titles):
            raise StudioError("The generated response contains duplicate or unknown sections.")
        if head is None and set(patches) != set(titles):
            raise StudioError("The first draft is missing required sections. Retry generation.")
        scoped = operation["section_id"]
        if scoped and set(patches) != {scoped}:
            raise StudioError("A section request attempted to change another section. No changes were applied.")
        sections = copy.deepcopy(head["sections"]) if head else []
        held = []
        for section_id, title in TEMPLATES[kind]:
            old = next((s for s in sections if s["id"] == section_id), None)
            if old and old.get("protected") and not scoped:
                if operation["action"] == "reconcile":
                    old["needs_review"] = True
                if section_id in patches:
                    held.append(title)
                continue
            if section_id in patches:
                value = {**patches[section_id], "title": title, "protected": bool(old and old.get("protected")), "needs_review": False, "unverified_source_ids": []}
                if old:
                    sections[sections.index(old)] = value
                else:
                    sections.append(value)
        # Evidence IDs are stable hashes, so unchanged sections retain valid citations across calls.
        merged_sources = {s["id"]: s for s in (head or {}).get("sources", []) + sources}
        for section in sections:
            unsupported = set(section["source_ids"]) - set(merged_sources)
            section["unverified_source_ids"] = sorted(set(section.get("unverified_source_ids", [])) | unsupported)
            section["source_ids"] = [s for s in section["source_ids"] if s in merged_sources]
        coverage = [c.model_dump() for c in generated.coverage] if kind == "rfc" else []
        questions = [q.model_dump() for q in generated.questions]
        assumptions = generated.assumptions
        if scoped and head:
            # A scoped patch cannot erase an unrelated review decision or uncertainty.
            coverage = head["coverage"]
            questions = [q for q in head["questions"] if q.get("section_id") != scoped] + [q for q in questions if q.get("section_id") == scoped]
            assumptions = list(dict.fromkeys(head["assumptions"] + assumptions))
        elif head:
            protected = {s["id"] for s in head["sections"] if s.get("protected")}
            retained = [q for q in head["questions"] if q.get("section_id") in protected]
            questions = [q for q in questions if q["id"] not in {r["id"] for r in retained}] + retained
        if kind == "rfc" and (len(coverage) != len(RFC_MODULES) or {c["module"] for c in coverage} != set(RFC_MODULES)):
            raise StudioError("The RFC must assess every conditional coverage area.")
        if len({q.id for q in generated.questions}) != len(generated.questions):
            raise StudioError("Open decisions need unique stable IDs.")
        candidate = {"kind": kind, "sections": sections, "pins": operation["pins"], "applied_summary": generated.summary,
                     "questions": questions,
                     "assumptions": assumptions, "coverage": coverage,
                     "sources": list(merged_sources.values()), "model": model, "protected_sections_kept": held}
        self._assign_ids(state, head, candidate)
        self._validate_refs(conn, candidate)
        if held:
            candidate["applied_summary"] += "\n\nYour direct edits were preserved in: " + ", ".join(held) + ". Choose that section in chat to revise it."
        return candidate

    def _validate_refs(self, conn, candidate):
        allowed_refs = {s["id"] for s in candidate["sources"]} | {i["id"] for s in candidate["sections"] for i in s["items"]}
        # Unsupported evidence stays explicitly provisional and blocks publication;
        # it must not be presented as a verified source or hide the useful draft.
        allowed_refs.update(ref for section in candidate["sections"] for ref in section.get("unverified_source_ids", []))
        for snapshot_id in candidate["pins"].values():
            # Pins were checked when the operation was queued and cannot be pruned.
            upstream = self.store.load_snapshot(conn, snapshot_id)
            allowed_refs.update(i["id"] for s in upstream["sections"] for i in s["items"])
        for section in candidate["sections"]:
            for item in section["items"]:
                if set(item["references"]) - allowed_refs:
                    raise StudioError(f"{item['id']} references an unavailable entity or source.")
def markdown(snapshot: dict, title: str) -> str:
    lines = [f"# {title}: {snapshot['kind'].upper()}", "", f"Version {snapshot['number']} • {snapshot['created_at']}", ""]
    if snapshot["pins"]:
        lines += ["Sources: " + ", ".join(f"{k.upper()} snapshot `{v}`" for k, v in snapshot["pins"].items()), ""]
    def cell(text):
        return text.replace("|", "\\|").replace("\n", "<br>")
    for section in snapshot["sections"]:
        lines += [f"## {section['title']}", "", section["body"], ""]
        if section.get("unverified_source_ids"):
            lines += ["> Evidence needs verification: " + ", ".join(section["unverified_source_ids"]), ""]
        if section["items"]:
            lines += ["| ID | Statement | Verification / outcome | References |", "| --- | --- | --- | --- |"]
            for item in section["items"]:
                lines.append("| " + " | ".join(cell(v) for v in [item["id"], item["statement"], item["verification"], ", ".join(item["references"])]) + " |")
            lines.append("")
    if snapshot["assumptions"]:
        lines += ["## Proposed assumptions", ""] + [f"- {a}" for a in snapshot["assumptions"]] + [""]
    if snapshot["questions"]:
        lines += ["## Open decisions", ""] + [f"- {'[Blocks publication] ' if q['blocking'] else ''}{q['question']} {q['why']}" for q in snapshot["questions"]] + [""]
    if snapshot["coverage"]:
        lines += ["## RFC coverage assessment", "", "| Area | Status | Rationale |", "| --- | --- | --- |"]
        lines += [f"| {c['module']} | {c['status']} | {cell(c['rationale'])} |" for c in snapshot["coverage"]] + [""]
    lines += ["## Source provenance", ""]
    lines += [f"- {s['id']}: {s['label']} (sha256 {s['sha256']}; {'excerpt' if s['truncated'] else 'complete'})" for s in snapshot["sources"]]
    return "\n".join(lines) + "\n"
