"""Files a tech spec's File Impact section names that no planned task owns.

The Architect sometimes leaves a File Impact file out of every task, and the
coverage verifier only runs for phased plans, so the gap surfaced only later in
`speed verify`. This check is deterministic: it reads the section and compares it
with the tasks' files_touched.

Usage: python3 lib/file_impact.py SPEC_TEXT_FILE TASKS_JSON_FILE
Prints a JSON list of unowned paths.
"""

from __future__ import annotations

import json
import posixpath
import re
import sys

CODE_EXTENSIONS = {
    "ts", "tsx", "js", "jsx", "mjs", "cjs", "py", "sh", "go", "rs", "java", "kt", "rb",
    "md", "json", "yaml", "yml", "toml", "sql", "css", "scss", "html", "vue", "svelte",
}
_TICKED = re.compile(r"`([^`\s]+)`")


def _is_file(token: str) -> bool:
    name = token.rsplit("/", 1)[-1]
    return "." in name and name.rsplit(".", 1)[1].lower() in CODE_EXTENSIONS


def file_impact_paths(spec_text: str) -> list[str]:
    """Paths listed under every `## File Impact` heading, in order, without duplicates.

    A bare name after a path on the same line (`a/b/x.ts`, `y.ts`) is taken from the
    same directory.
    """
    paths: list[str] = []
    in_section = False
    for line in spec_text.splitlines():
        if line.startswith("## "):
            in_section = line.strip().lower() == "## file impact"
            continue
        if not in_section:
            continue
        directory = ""
        for token in _TICKED.findall(line):
            if not _is_file(token):
                continue
            if "/" in token:
                path = token.lstrip("./")
                directory = posixpath.dirname(path)
            elif directory:
                path = posixpath.join(directory, token)
            else:
                continue  # a bare name with no directory on the line is ambiguous
            if path not in paths:
                paths.append(path)
    return paths


def unowned_paths(spec_text: str, tasks: list[dict]) -> list[str]:
    owned = {f.lstrip("./") for t in tasks for f in (t.get("files_touched") or [])}
    return [p for p in file_impact_paths(spec_text) if p not in owned]


def main(argv: list[str]) -> int:
    spec_text = open(argv[1], encoding="utf-8").read()
    data = json.load(open(argv[2], encoding="utf-8"))
    tasks = data.get("tasks", data) if isinstance(data, dict) else data
    print(json.dumps(unowned_paths(spec_text, tasks)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
