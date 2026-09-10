"""Lossless author editing of document content, separate from export/audit metadata."""
import copy
import html
import re
from uuid import uuid4

import mistune
from mistune.plugins.table import table as table_plugin

from .models import Coverage, Item, Question, RFC_MODULES, Section, TEMPLATES

ITEM_COLUMNS = ["ID", "Statement", "Verification / outcome", "References"]
EXTRAS = {
    "Proposed assumptions": ("assumptions", ["Assumption"]),
    "Open questions": ("questions", ["ID", "Question", "Why", "Blocking", "Section"]),
    "RFC coverage": ("coverage", ["Area", "Status", "Rationale"]),
}


class LocatedBlocks(mistune.BlockParser):
    """Locate top-level blocks without mistaking fenced code/lists for sections."""
    def parse_method(self, match, state):
        start, count = match.start(), len(state.tokens)
        end = super().parse_method(match, state)
        if end and not state.parent and len(state.tokens) > count and match.lastgroup in ("atx_heading", "table", "nptable"):
            state.tokens[-1]["span"] = (start, end)
        return end


def blocks(text):
    parser = mistune.Markdown(block=LocatedBlocks(), plugins=[table_plugin])
    state = parser.block.state_cls()
    state.process(text if text.endswith("\n") else text + "\n")
    parser.block.parse(state)
    return state.tokens


def cell(value):
    value = html.escape(str(value), quote=False).replace("|", "&#124;").replace("\n", "&#10;").replace("\t", "&#9;")
    return re.sub(r"^ +| +$", lambda m: "&#32;" * len(m.group()), value)


def body_for_editor(body):
    # Top-level # belongs to document sections. Keep a generated internal heading
    # within its section; a no-op roundtrip below restores its exact stored bytes.
    for token in reversed(blocks(body)):
        if token["type"] == "heading" and token["attrs"]["level"] == 1 and "span" in token:
            start = token["span"][0]
            start += len(body[start:]) - len(body[start:].lstrip(" "))
            body = body[:start] + "#" + body[start:]
    return body


def table(columns, rows):
    return "\n".join(["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
                     + ["| " + " | ".join(cell(v) for v in row) + " |" for row in rows])


def editable_markdown(snapshot):
    parts = []
    for section in snapshot["sections"]:
        text = f"# {section['title']}\n\n{body_for_editor(section['body'])}"
        if section["items"]:
            text += "\n\n" + table(ITEM_COLUMNS, [[i["id"], i["statement"], i["verification"], ", ".join(i["references"])] for i in section["items"]])
        parts.append(text)
    if snapshot["assumptions"]:
        parts.append("# Proposed assumptions\n\n" + table(EXTRAS["Proposed assumptions"][1], [[a] for a in snapshot["assumptions"]]))
    if snapshot["questions"]:
        parts.append("# Open questions\n\n" + table(EXTRAS["Open questions"][1], [[q["id"], q["question"], q["why"], str(q["blocking"]).lower(), q.get("section_id", "")] for q in snapshot["questions"]]))
    if snapshot["coverage"]:
        parts.append("# RFC coverage\n\n" + table(EXTRAS["RFC coverage"][1], [[c["module"], c["status"], c["rationale"]] for c in snapshot["coverage"]]))
    return "\n\n".join(parts) + "\n"


def row_cells(line):
    # GFM requires a pipe within a cell to be escaped, even in inline code.
    values = []
    current = ""
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and (len(line[:-1]) - len(line[:-1].rstrip("\\"))) % 2 == 0:
        line = line[:-1]
    for char in line:
        if char == "|" and (len(current) - len(current.rstrip("\\"))) % 2 == 0:
            values.append(current.strip()); current = ""
        else:
            current += char
    values.append(current.strip())
    return [html.unescape(re.sub(r"<br\s*/?>", "\n", v, flags=re.I).replace(r"\|", "|")) for v in values]


def extract_table(text, columns):
    found = []
    for token in blocks(text):
        if token["type"] != "table" or "span" not in token:
            continue
        start, end = token["span"]
        lines = text[start:end].strip().splitlines()
        if row_cells(lines[0]) == columns:
            rows = [row_cells(line) for line in lines[2:]]
            if any(len(row) != len(columns) for row in rows):
                raise ValueError("A table row has the wrong number of cells. Escape a pipe inside text as \\|.")
            found.append((start, end, rows))
    if len(found) > 1:
        raise ValueError("Keep the structured entries in one table per section.")
    if not found:
        return text, None
    start, end, rows = found[0]
    return (text[:start] + text[end:]).strip(), rows


def parse_edit(markdown, head):
    """Apply one author draft atomically; reject ambiguity instead of dropping content."""
    text = markdown.replace("\r\n", "\n").replace("\r", "\n")
    headings = [t for t in blocks(text) if t["type"] == "heading" and t["attrs"]["level"] == 1 and "span" in t]
    if not headings or text[:headings[0]["span"][0]].strip():
        raise ValueError("Start the document with a # section heading. Use ## for a subsection.")
    known = {s["title"]: s for s in head["sections"]}
    candidate = copy.deepcopy(head)
    candidate.update(sections=[], assumptions=[], questions=[], coverage=[])
    seen = set()
    for index, heading in enumerate(headings):
        title = heading["text"]
        if title in seen or not title or len(title) > 160:
            raise ValueError(f"Use a unique section heading of 1–160 characters: {title}.")
        seen.add(title)
        body = text[heading["span"][1]:headings[index + 1]["span"][0] if index + 1 < len(headings) else len(text)].strip()
        if title in EXTRAS:
            key, columns = EXTRAS[title]
            rest, rows = extract_table(body, columns)
            if rest or rows is None:
                raise ValueError(f"Keep {title} in its table with these columns: {', '.join(columns)}.")
            if key == "assumptions":
                candidate[key] = [r[0] for r in rows if r[0].strip()]
            elif key == "questions":
                if any(r[3] not in ("true", "false") for r in rows):
                    raise ValueError("Open questions: Blocking must be true or false.")
                candidate[key] = [Question(id=r[0] if r[0] and r[0] != "new" else uuid4().hex, question=r[1], why=r[2], blocking=r[3] == "true", section_id=r[4]).model_dump() for r in rows]
            else:
                candidate[key] = [Coverage(module=r[0], status=r[1], rationale=r[2]).model_dump() for r in rows]
            continue
        previous = known.get(title)
        section = copy.deepcopy(previous) if previous else {"id": "custom-" + uuid4().hex, "title": title, "source_ids": [], "protected": True, "needs_review": False, "unverified_source_ids": []}
        body, rows = extract_table(body, ITEM_COLUMNS)
        if rows is None and previous and previous["items"]:
            raise ValueError(f"Keep the entries table in {title}, including its column headings. Remove rows inside the table if needed.")
        items = [Item(id=r[0] if r[0] and r[0] != "new" else "new-" + uuid4().hex, statement=r[1], verification=r[2], references=[ref.strip() for ref in r[3].split(",") if ref.strip()]).model_dump() for r in rows or []]
        # Do not trim untouched source text or protect sections just from opening the editor.
        if previous and body == body_for_editor(previous["body"]).strip():
            body = previous["body"]
        Section(id=section["id"], body=body, items=items, source_ids=section["source_ids"])
        changed = not previous or body != previous["body"] or items != previous["items"]
        section.update(body=body, items=items)
        if changed:
            section.update(protected=True, needs_review=False)
        candidate["sections"].append(section)
    missing = [s["title"] for s in head["sections"] if s["id"] in dict(TEMPLATES[head["kind"]]) and s["title"] not in seen]
    if missing:
        raise ValueError("Keep the required section headings: " + ", ".join(missing) + ". You can add other sections with # and subsections with ##.")
    if len(candidate["sections"]) > 30 or len(candidate["assumptions"]) > 30 or len(candidate["questions"]) > 30:
        raise ValueError("Use at most 30 sections, assumptions or open questions.")
    questions = candidate["questions"]
    if len({q["id"] for q in questions}) != len(questions):
        raise ValueError("Each open question needs a unique ID.")
    if any(q["section_id"] and q["section_id"] not in {s["id"] for s in candidate["sections"]} for q in questions):
        raise ValueError("An open question refers to a section that is no longer in the document.")
    coverage = candidate["coverage"]
    if head["kind"] == "rfc" and (len(coverage) != len(RFC_MODULES) or {c["module"] for c in coverage} != set(RFC_MODULES)):
        raise ValueError("Keep every area in the RFC coverage table and record its status and rationale.")
    if head["kind"] != "rfc" and coverage:
        raise ValueError("RFC coverage belongs in an RFC.")
    return candidate
