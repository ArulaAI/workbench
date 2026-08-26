# SPEED Skill System — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the first vertical slice of the SPEED skill system: a canonical `skills/` catalog, a stdlib-only Python projection engine, managed-file identity, and `speed skills sync|status` that projects a minimal `workbench-draft` package into `.claude/skills/`.

**Architecture:** A self-contained Python package at `lib/skills/` does discovery, validation, pure rendering, and manifest-backed state classification. A thin bash wrapper `lib/cmd/skills.sh` resolves the interpreter and catalog version and calls `python -m skills`. `render()` is pure (returns bytes); `sync()` is the sole writer. Managed-file identity is per-file SHA-256 recorded in `.speed/skills/manifest.json`, so sync never overwrites a user-edited projection.

**Tech Stack:** Python 3.11 stdlib only (`hashlib`, `json`, `pathlib`, `argparse`, `dataclasses`); bash for CLI dispatch; pytest 9.1.1 (already in the install `.venv`) for tests.

**Spec:** `specs/tech/speed-skill-system.md` (RFC). Product context: `specs/product/speed-skill-system-prd.md`.

## Global Constraints

- **Stdlib only.** No new entries in `requirements.txt`. The engine parses only `SKILL.md` front matter (simple `key: value` + folded `>` blocks) and copies every other file byte-for-byte. PyYAML exists in the venv but is intentionally not depended on.
- **`render()` is pure.** It returns `dict[str, bytes]` and never touches the filesystem. `sync()` is the only module that writes.
- **Determinism.** Given identical inputs, `render()` returns byte-identical output; a second `sync()` with an unchanged catalog writes nothing.
- **Never overwrite user edits.** A projected file whose on-disk hash differs from its manifest hash is `conflicted` and is preserved unless `--force`.
- **Bounded writes.** Sync writes only under a detected surface root (`.claude/skills/…`) and `.speed/skills/manifest.json`. Nothing else in `.claude/` is touched.
- **Skill name rule:** `^[a-z0-9][a-z0-9-]*$`, equal to the package directory name.
- **Provenance keys injected into every projected `SKILL.md`:** `x-speed-managed: true`, `x-speed-source: <skill-name>`, `x-speed-catalog-version: <version>`.
- **Invocation form:** `PYTHONPATH="${SPEED_DIR}/lib" <python> -m skills <sub> …` (because `lib/` is not a package; `lib/skills/` is).
- **Surfaces in Phase 1:** `claude_code` only (`.claude/skills/`). Codex is Phase 3.
- **State vocabulary:** `absent`, `current`, `stale`, `conflicted`, `orphaned`, `unsupported`.

---

## File Structure

```
skills/                              # canonical catalog (NEW, at repo root, = SPEED_DIR/skills)
└── workbench-draft/
    └── SKILL.md                     # minimal valid package (full body owned by 03-guided-authoring)

lib/skills/                          # projection engine (NEW self-contained package)
├── __init__.py                      # package marker; State constants; SURFACE ids
├── __main__.py                      # argparse CLI: `sync`, `status`
├── frontmatter.py                   # parse()/serialize() for SKILL.md front matter
├── catalog.py                       # SkillPackage; load_package(); load_catalog()
├── validate.py                      # Violation; validate_package(); validate_catalog()
├── targets.py                       # Surface; SURFACES; detect_surfaces(); dest_dir()
├── project.py                       # render(pkg, surface, version) -> dict[str, bytes]
├── manifest.py                      # hashing; load/save; classify_skill()
└── sync.py                          # SkillState; sync(); status()

lib/cmd/skills.sh                    # NEW bash wrapper defining cmd_skills()
speed                                # MODIFY: add `skills)` case
lib/cmd/project.sh                   # MODIFY: cmd_init calls projection step (non-fatal)

tests/skills/                        # NEW
├── conftest.py                      # tmp_catalog / tmp_project fixtures
├── test_frontmatter.py
├── test_catalog.py
├── test_validate.py
├── test_targets.py
├── test_project.py
├── test_manifest.py
├── test_sync.py
└── test_cli_e2e.py
```

**Test command (from repo root):**
```bash
PYTHONPATH="$(pwd)/lib" /Users/mohitpatel/Desktop/inrhythm/SPEED/.venv/bin/python3 -m pytest tests/skills/ -v
```

---

### Task 1: Front-matter parse/serialize

**Files:**
- Create: `lib/skills/__init__.py`
- Create: `lib/skills/frontmatter.py`
- Test: `tests/skills/test_frontmatter.py`

**Interfaces:**
- Produces:
  - `parse(text: str) -> tuple[dict[str, str], str]` — returns `(meta, body)`. Front matter is the block between a leading `---` line and the next `---`. Supports `key: value` and folded scalars introduced by `key: >` (following more-indented lines joined with spaces). No front matter → `({}, text)`.
  - `serialize(meta: dict[str, str], body: str) -> str` — emits `---\n<key: value per line, insertion order>\n---\n\n<body>`. Values containing a newline are written as folded `>` blocks. Deterministic.

- [ ] **Step 1: Write the failing test**

```python
# tests/skills/test_frontmatter.py
from skills.frontmatter import parse, serialize

SAMPLE = """---
name: workbench-draft
description: >
  Run a guided interview
  and draft a spec.
---

# workbench-draft
Body line.
"""

def test_parse_extracts_scalar_and_folded():
    meta, body = parse(SAMPLE)
    assert meta["name"] == "workbench-draft"
    assert meta["description"] == "Run a guided interview and draft a spec."
    assert body.startswith("# workbench-draft")

def test_parse_no_frontmatter_returns_empty_meta():
    meta, body = parse("# just a doc\n")
    assert meta == {}
    assert body == "# just a doc\n"

def test_serialize_roundtrip_is_stable():
    meta = {"name": "x", "description": "one two"}
    out = serialize(meta, "# Body\n")
    meta2, body2 = parse(out)
    assert meta2 == meta
    assert body2.strip() == "# Body"
    assert serialize(meta, "# Body\n") == out  # deterministic
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH="$(pwd)/lib" .venv/bin/python3 -m pytest tests/skills/test_frontmatter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'skills.frontmatter'`

- [ ] **Step 3: Write minimal implementation**

```python
# lib/skills/__init__.py
"""SPEED skill system: canonical catalog projection engine."""
```

```python
# lib/skills/frontmatter.py
from __future__ import annotations

_FENCE = "---"


def parse(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != _FENCE:
        return {}, text
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == _FENCE:
            end = i
            break
    if end is None:
        return {}, text
    meta = _parse_block([ln.rstrip("\n") for ln in lines[1:end]])
    body = "".join(lines[end + 1:])
    body = body[1:] if body.startswith("\n") else body
    return meta, body


def _parse_block(raw: list[str]) -> dict[str, str]:
    meta: dict[str, str] = {}
    i = 0
    while i < len(raw):
        line = raw[i]
        if not line.strip():
            i += 1
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if val == ">":
            folded: list[str] = []
            i += 1
            while i < len(raw) and (raw[i].startswith((" ", "\t")) or not raw[i].strip()):
                if raw[i].strip():
                    folded.append(raw[i].strip())
                i += 1
            meta[key] = " ".join(folded)
        else:
            meta[key] = val
            i += 1
    return meta


def serialize(meta: dict[str, str], body: str) -> str:
    out = [_FENCE]
    for key, val in meta.items():
        if "\n" in val:
            out.append(f"{key}: >")
            for part in val.split("\n"):
                out.append(f"  {part}")
        else:
            out.append(f"{key}: {val}")
    out.append(_FENCE)
    out.append("")
    return "\n".join(out) + "\n" + body.lstrip("\n")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH="$(pwd)/lib" .venv/bin/python3 -m pytest tests/skills/test_frontmatter.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add lib/skills/__init__.py lib/skills/frontmatter.py tests/skills/test_frontmatter.py
git commit -m "feat(skills): stdlib front-matter parse/serialize"
```

---

### Task 2: Catalog loading

**Files:**
- Create: `lib/skills/catalog.py`
- Test: `tests/skills/test_catalog.py`, `tests/skills/conftest.py`

**Interfaces:**
- Consumes: `skills.frontmatter.parse`
- Produces:
  - `@dataclass SkillPackage`: `name: str`, `root: Path`, `meta: dict[str, str]`, `body: str`, `files: dict[str, bytes]` (every file under `root`, relpath-keyed, includes `SKILL.md` raw bytes).
  - `load_package(pkg_dir: Path) -> SkillPackage`
  - `load_catalog(skills_dir: Path) -> list[SkillPackage]` — each immediate subdir containing `SKILL.md`, sorted by name. Missing `skills_dir` → `[]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/skills/conftest.py
import pytest

@pytest.fixture
def tmp_catalog(tmp_path):
    def _make(name="workbench-draft", extra=None):
        pkg = tmp_path / "skills" / name
        (pkg / "references").mkdir(parents=True)
        (pkg / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: A test skill\n---\n\n# {name}\nDo the thing.\n"
        )
        (pkg / "references" / "notes.md").write_text("ref body\n")
        for rel, content in (extra or {}).items():
            p = pkg / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
        return tmp_path / "skills"
    return _make

@pytest.fixture
def tmp_project(tmp_path):
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True)   # marks claude_code as detected
    return proj
```

```python
# tests/skills/test_catalog.py
from skills.catalog import load_catalog, load_package

def test_load_package_reads_meta_body_and_files(tmp_catalog):
    skills_dir = tmp_catalog()
    pkg = load_package(skills_dir / "workbench-draft")
    assert pkg.name == "workbench-draft"
    assert pkg.meta["description"] == "A test skill"
    assert "SKILL.md" in pkg.files
    assert pkg.files["references/notes.md"] == b"ref body\n"

def test_load_catalog_discovers_and_sorts(tmp_catalog):
    skills_dir = tmp_catalog()
    tmp_catalog(name="another-skill")  # same tmp_path/skills parent
    names = [p.name for p in load_catalog(skills_dir)]
    assert names == ["another-skill", "workbench-draft"]

def test_load_catalog_missing_dir_is_empty(tmp_path):
    assert load_catalog(tmp_path / "nope") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH="$(pwd)/lib" .venv/bin/python3 -m pytest tests/skills/test_catalog.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'skills.catalog'`

- [ ] **Step 3: Write minimal implementation**

```python
# lib/skills/catalog.py
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from skills.frontmatter import parse


@dataclass
class SkillPackage:
    name: str
    root: Path
    meta: dict
    body: str
    files: dict = field(default_factory=dict)


def _read_files(root: Path) -> dict:
    files: dict = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            files[p.relative_to(root).as_posix()] = p.read_bytes()
    return files


def load_package(pkg_dir: Path) -> SkillPackage:
    skill_md = pkg_dir / "SKILL.md"
    meta, body = parse(skill_md.read_text()) if skill_md.exists() else ({}, "")
    return SkillPackage(
        name=pkg_dir.name,
        root=pkg_dir,
        meta=meta,
        body=body,
        files=_read_files(pkg_dir),
    )


def load_catalog(skills_dir: Path) -> list[SkillPackage]:
    if not skills_dir.is_dir():
        return []
    pkgs = []
    for child in sorted(skills_dir.iterdir()):
        if child.is_dir() and (child / "SKILL.md").exists():
            pkgs.append(load_package(child))
    return pkgs
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH="$(pwd)/lib" .venv/bin/python3 -m pytest tests/skills/test_catalog.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add lib/skills/catalog.py tests/skills/conftest.py tests/skills/test_catalog.py
git commit -m "feat(skills): canonical catalog discovery and loading"
```

---

### Task 3: Package validation

**Files:**
- Create: `lib/skills/validate.py`
- Test: `tests/skills/test_validate.py`

**Interfaces:**
- Consumes: `skills.catalog.SkillPackage`, `load_catalog`
- Produces:
  - `@dataclass Violation`: `package: str`, `path: str | None`, `reason: str`
  - `validate_package(pkg: SkillPackage) -> list[Violation]` — checks: `SKILL.md` present; `name` non-empty and matches `^[a-z0-9][a-z0-9-]*$`; `meta["name"] == pkg.name`; `description` non-empty; no file relpath contains `..` or is absolute.
  - `validate_catalog(pkgs: list[SkillPackage]) -> list[Violation]` — per-package violations plus duplicate-name detection.

- [ ] **Step 1: Write the failing test**

```python
# tests/skills/test_validate.py
from pathlib import Path
from skills.catalog import SkillPackage
from skills.validate import validate_package, validate_catalog

def _pkg(name="workbench-draft", meta=None, files=None):
    meta = meta if meta is not None else {"name": name, "description": "ok"}
    files = files if files is not None else {"SKILL.md": b"..."}
    return SkillPackage(name=name, root=Path("/x")/name, meta=meta, body="b", files=files)

def test_valid_package_has_no_violations():
    assert validate_package(_pkg()) == []

def test_name_dir_mismatch_flagged():
    v = validate_package(_pkg(meta={"name": "other", "description": "ok"}))
    assert any("name" in x.reason for x in v)

def test_bad_name_charset_flagged():
    v = validate_package(_pkg(name="Bad_Name", meta={"name": "Bad_Name", "description": "ok"}))
    assert any(x.reason for x in v)

def test_missing_description_flagged():
    v = validate_package(_pkg(meta={"name": "workbench-draft", "description": ""}))
    assert any("description" in x.reason for x in v)

def test_missing_skill_md_flagged():
    v = validate_package(_pkg(files={}))
    assert any("SKILL.md" in x.reason for x in v)

def test_path_traversal_flagged():
    v = validate_package(_pkg(files={"SKILL.md": b".", "../evil.md": b"x"}))
    assert any(".." in (x.path or "") for x in v)

def test_duplicate_names_flagged():
    v = validate_catalog([_pkg(), _pkg()])
    assert any("duplicate" in x.reason.lower() for x in v)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH="$(pwd)/lib" .venv/bin/python3 -m pytest tests/skills/test_validate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'skills.validate'`

- [ ] **Step 3: Write minimal implementation**

```python
# lib/skills/validate.py
from __future__ import annotations

import re
from dataclasses import dataclass

from skills.catalog import SkillPackage

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@dataclass
class Violation:
    package: str
    path: str | None
    reason: str


def validate_package(pkg: SkillPackage) -> list[Violation]:
    out: list[Violation] = []
    if "SKILL.md" not in pkg.files:
        out.append(Violation(pkg.name, "SKILL.md", "missing SKILL.md"))
    if not _NAME_RE.match(pkg.name or ""):
        out.append(Violation(pkg.name, None, f"invalid skill name '{pkg.name}'"))
    declared = pkg.meta.get("name", "")
    if declared != pkg.name:
        out.append(Violation(pkg.name, "SKILL.md",
                             f"front-matter name '{declared}' != directory '{pkg.name}'"))
    if not pkg.meta.get("description", "").strip():
        out.append(Violation(pkg.name, "SKILL.md", "empty or missing description"))
    for rel in pkg.files:
        if rel.startswith("/") or ".." in rel.split("/"):
            out.append(Violation(pkg.name, rel, "unsafe path escapes package"))
    return out


def validate_catalog(pkgs: list[SkillPackage]) -> list[Violation]:
    out: list[Violation] = []
    seen: dict[str, int] = {}
    for pkg in pkgs:
        out.extend(validate_package(pkg))
        seen[pkg.name] = seen.get(pkg.name, 0) + 1
    for name, count in seen.items():
        if count > 1:
            out.append(Violation(name, None, f"duplicate skill name '{name}'"))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH="$(pwd)/lib" .venv/bin/python3 -m pytest tests/skills/test_validate.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add lib/skills/validate.py tests/skills/test_validate.py
git commit -m "feat(skills): package + catalog validation contract"
```

---

### Task 4: Surface targets and detection

**Files:**
- Create: `lib/skills/targets.py`
- Test: `tests/skills/test_targets.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) Surface`: `id: str`, `skills_root: str`, `marker: str`
  - `SURFACES: list[Surface]` = `[Surface("claude_code", ".claude/skills", ".claude")]`
  - `detect_surfaces(project_root: Path) -> list[Surface]` — a surface is detected when `project_root / marker` is a dir.
  - `dest_dir(surface: Surface, skill_name: str, project_root: Path) -> Path`

- [ ] **Step 1: Write the failing test**

```python
# tests/skills/test_targets.py
from skills.targets import detect_surfaces, dest_dir, SURFACES

def test_claude_detected_when_dot_claude_present(tmp_project):
    ids = [s.id for s in detect_surfaces(tmp_project)]
    assert ids == ["claude_code"]

def test_no_surface_when_absent(tmp_path):
    assert detect_surfaces(tmp_path) == []

def test_dest_dir_layout(tmp_project):
    s = SURFACES[0]
    d = dest_dir(s, "workbench-draft", tmp_project)
    assert d == tmp_project / ".claude" / "skills" / "workbench-draft"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH="$(pwd)/lib" .venv/bin/python3 -m pytest tests/skills/test_targets.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'skills.targets'`

- [ ] **Step 3: Write minimal implementation**

```python
# lib/skills/targets.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Surface:
    id: str
    skills_root: str
    marker: str


SURFACES: list[Surface] = [
    Surface(id="claude_code", skills_root=".claude/skills", marker=".claude"),
]


def detect_surfaces(project_root: Path) -> list[Surface]:
    return [s for s in SURFACES if (project_root / s.marker).is_dir()]


def dest_dir(surface: Surface, skill_name: str, project_root: Path) -> Path:
    return project_root / surface.skills_root / skill_name
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH="$(pwd)/lib" .venv/bin/python3 -m pytest tests/skills/test_targets.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add lib/skills/targets.py tests/skills/test_targets.py
git commit -m "feat(skills): surface targets and detection (claude_code)"
```

---

### Task 5: Pure projection render

**Files:**
- Create: `lib/skills/project.py`
- Test: `tests/skills/test_project.py`

**Interfaces:**
- Consumes: `skills.catalog.SkillPackage`, `skills.targets.Surface`, `skills.frontmatter.serialize`
- Produces:
  - `render(pkg: SkillPackage, surface: Surface, catalog_version: str) -> dict[str, bytes]` — returns relpath→bytes for the projection. `SKILL.md` re-serialized with the package meta plus injected provenance keys (`x-speed-managed`, `x-speed-source`, `x-speed-catalog-version`); all other files copied verbatim. Deterministic.

- [ ] **Step 1: Write the failing test**

```python
# tests/skills/test_project.py
from skills.catalog import load_package
from skills.targets import SURFACES
from skills.project import render
from skills.frontmatter import parse

def test_render_injects_provenance_and_keeps_refs(tmp_catalog):
    skills_dir = tmp_catalog()
    pkg = load_package(skills_dir / "workbench-draft")
    out = render(pkg, SURFACES[0], "0.3.0")
    assert "references/notes.md" in out
    assert out["references/notes.md"] == b"ref body\n"
    meta, body = parse(out["SKILL.md"].decode())
    assert meta["name"] == "workbench-draft"
    assert meta["x-speed-managed"] == "true"
    assert meta["x-speed-source"] == "workbench-draft"
    assert meta["x-speed-catalog-version"] == "0.3.0"
    assert "Do the thing." in body

def test_render_is_deterministic(tmp_catalog):
    skills_dir = tmp_catalog()
    pkg = load_package(skills_dir / "workbench-draft")
    assert render(pkg, SURFACES[0], "0.3.0") == render(pkg, SURFACES[0], "0.3.0")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH="$(pwd)/lib" .venv/bin/python3 -m pytest tests/skills/test_project.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'skills.project'`

- [ ] **Step 3: Write minimal implementation**

```python
# lib/skills/project.py
from __future__ import annotations

from skills.catalog import SkillPackage
from skills.frontmatter import serialize
from skills.targets import Surface


def render(pkg: SkillPackage, surface: Surface, catalog_version: str) -> dict:
    out: dict = {}
    for rel, content in pkg.files.items():
        if rel != "SKILL.md":
            out[rel] = content
    meta = dict(pkg.meta)
    meta["x-speed-managed"] = "true"
    meta["x-speed-source"] = pkg.name
    meta["x-speed-catalog-version"] = catalog_version
    out["SKILL.md"] = serialize(meta, pkg.body).encode()
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH="$(pwd)/lib" .venv/bin/python3 -m pytest tests/skills/test_project.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add lib/skills/project.py tests/skills/test_project.py
git commit -m "feat(skills): pure projection render with provenance injection"
```

---

### Task 6: Manifest hashing and state classification

**Files:**
- Create: `lib/skills/manifest.py`
- Test: `tests/skills/test_manifest.py`

**Interfaces:**
- Produces:
  - `hash_bytes(b: bytes) -> str` → `"sha256:<hex>"`
  - `hash_disk(dest: Path) -> dict[str, str]` — relpath→hash of every file under `dest` (empty dict if `dest` absent)
  - `load_manifest(project_root: Path) -> dict` / `save_manifest(project_root: Path, data: dict) -> None` — file at `.speed/skills/manifest.json`
  - `classify_skill(rendered: dict[str, bytes] | None, disk: dict[str, str], entry: dict | None) -> str` — returns a state constant. `rendered is None` means "not in catalog" (orphan candidate).
- State constants live in `skills/__init__.py`: `ABSENT, CURRENT, STALE, CONFLICTED, ORPHANED = "absent","current","stale","conflicted","orphaned"`.

**Classification logic (single source of truth):**
- `rendered is None`: if `disk` empty → nothing (skip); elif `disk == entry.files` → `ORPHANED` (safe remove); else → `CONFLICTED`.
- `entry is None` and `disk` empty → `ABSENT`.
- `entry is None` and `disk` non-empty → `CONFLICTED` (unknown pre-existing files; never blind-overwrite).
- `disk != entry.files` → `CONFLICTED` (user edited).
- `disk == entry.files` and `hash(rendered) == entry.files` → `CURRENT`.
- `disk == entry.files` and `hash(rendered) != entry.files` → `STALE` (catalog advanced, projection unmodified).

- [ ] **Step 1: Write the failing test**

```python
# tests/skills/test_manifest.py
from skills.manifest import hash_bytes, classify_skill
from skills import CURRENT, STALE, CONFLICTED, ORPHANED, ABSENT

def _hashes(d):  # rendered dict -> hash map
    return {k: hash_bytes(v) for k, v in d.items()}

R = {"SKILL.md": b"v1", "references/n.md": b"ref"}

def test_absent():
    assert classify_skill(R, {}, None) == ABSENT

def test_current():
    entry = {"files": _hashes(R)}
    assert classify_skill(R, _hashes(R), entry) == CURRENT

def test_stale_when_catalog_changed_but_disk_unmodified():
    entry = {"files": _hashes(R)}
    R2 = {"SKILL.md": b"v2", "references/n.md": b"ref"}
    assert classify_skill(R2, _hashes(R), entry) == STALE

def test_conflicted_when_disk_edited():
    entry = {"files": _hashes(R)}
    disk = dict(_hashes(R)); disk["SKILL.md"] = hash_bytes(b"user-edit")
    assert classify_skill(R, disk, entry) == CONFLICTED

def test_conflicted_when_unknown_preexisting_files():
    assert classify_skill(R, _hashes(R), None) == CONFLICTED

def test_orphaned_when_removed_and_unmodified():
    entry = {"files": _hashes(R)}
    assert classify_skill(None, _hashes(R), entry) == ORPHANED

def test_orphaned_edited_downgrades_to_conflicted():
    entry = {"files": _hashes(R)}
    disk = dict(_hashes(R)); disk["SKILL.md"] = hash_bytes(b"user-edit")
    assert classify_skill(None, disk, entry) == CONFLICTED
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH="$(pwd)/lib" .venv/bin/python3 -m pytest tests/skills/test_manifest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'skills.manifest'`

- [ ] **Step 3: Write minimal implementation**

Add state constants to `lib/skills/__init__.py`:

```python
# lib/skills/__init__.py  (append)
ABSENT = "absent"
CURRENT = "current"
STALE = "stale"
CONFLICTED = "conflicted"
ORPHANED = "orphaned"
UNSUPPORTED = "unsupported"
```

```python
# lib/skills/manifest.py
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from skills import ABSENT, CURRENT, STALE, CONFLICTED, ORPHANED

_MANIFEST_REL = ".speed/skills/manifest.json"


def hash_bytes(b: bytes) -> str:
    return "sha256:" + hashlib.sha256(b).hexdigest()


def hash_disk(dest: Path) -> dict:
    out: dict = {}
    if not dest.is_dir():
        return out
    for p in sorted(dest.rglob("*")):
        if p.is_file():
            out[p.relative_to(dest).as_posix()] = hash_bytes(p.read_bytes())
    return out


def load_manifest(project_root: Path) -> dict:
    path = project_root / _MANIFEST_REL
    if path.exists():
        return json.loads(path.read_text())
    return {"catalog_version": None, "surfaces": {}}


def save_manifest(project_root: Path, data: dict) -> None:
    path = project_root / _MANIFEST_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def _rendered_hashes(rendered: dict) -> dict:
    return {k: hash_bytes(v) for k, v in rendered.items()}


def classify_skill(rendered: dict | None, disk: dict, entry: dict | None) -> str:
    recorded = (entry or {}).get("files", {})
    if rendered is None:
        if not disk:
            return CURRENT  # nothing on disk, nothing to do; caller filters
        return ORPHANED if disk == recorded else CONFLICTED
    if entry is None:
        return ABSENT if not disk else CONFLICTED
    if disk != recorded:
        return CONFLICTED
    return CURRENT if _rendered_hashes(rendered) == recorded else STALE
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH="$(pwd)/lib" .venv/bin/python3 -m pytest tests/skills/test_manifest.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add lib/skills/__init__.py lib/skills/manifest.py tests/skills/test_manifest.py
git commit -m "feat(skills): manifest hashing and six-state classification"
```

---

### Task 7: Sync/status orchestration + CLI

**Files:**
- Create: `lib/skills/sync.py`
- Create: `lib/skills/__main__.py`
- Test: `tests/skills/test_sync.py`

**Interfaces:**
- Consumes: `catalog.load_catalog`, `validate.validate_catalog`, `targets.detect_surfaces`/`dest_dir`, `project.render`, `manifest.*`
- Produces:
  - `@dataclass SkillState`: `surface: str`, `skill: str`, `state: str`, `action: str`
  - `sync(project_root: Path, skills_dir: Path, catalog_version: str, *, force=False, only_surface=None) -> list[SkillState]` — detect surfaces, classify each catalog skill + orphans, apply writes/removals for `absent`/`stale` (and `conflicted` only when `force`), rewrite manifest. Sole writer.
  - `status(project_root, skills_dir, catalog_version, *, only_surface=None) -> list[SkillState]` — classify only, no writes; when no surface detected returns one `UNSUPPORTED` row per known surface.
  - `__main__.main(argv) -> int` — argparse `sync`/`status`; exit codes: sync `0` ok / `2` conflicts remain / `3` error; status `0` all current / `1` drift present / `3` error. `--json` prints machine output.

- [ ] **Step 1: Write the failing test**

```python
# tests/skills/test_sync.py
from skills.sync import sync, status
from skills import CURRENT, STALE, CONFLICTED, ABSENT

def _run(project, skills_dir, version="0.3.0", **kw):
    return {s.skill + "@" + s.surface: s for s in sync(project, skills_dir, version, **kw)}

def test_sync_projects_then_idempotent(tmp_catalog, tmp_project):
    skills_dir = tmp_catalog()
    first = _run(tmp_project, skills_dir)
    proj_skill = tmp_project / ".claude" / "skills" / "workbench-draft" / "SKILL.md"
    assert proj_skill.exists()
    assert first["workbench-draft@claude_code"].state == ABSENT  # pre-write classification
    # second run: nothing to do
    again = status(tmp_project, skills_dir, "0.3.0")
    assert all(s.state == CURRENT for s in again)

def test_sync_preserves_user_edit_as_conflict(tmp_catalog, tmp_project):
    skills_dir = tmp_catalog()
    _run(tmp_project, skills_dir)
    edited = tmp_project / ".claude" / "skills" / "workbench-draft" / "SKILL.md"
    edited.write_text("HAND EDITED\n")
    rows = status(tmp_project, skills_dir, "0.3.0")
    assert any(s.state == CONFLICTED for s in rows)
    # sync without force must not clobber
    _run(tmp_project, skills_dir)
    assert edited.read_text() == "HAND EDITED\n"
    # force overwrites
    _run(tmp_project, skills_dir, force=True)
    assert "HAND EDITED" not in edited.read_text()

def test_version_bump_marks_stale_then_updates(tmp_catalog, tmp_project):
    skills_dir = tmp_catalog()
    _run(tmp_project, skills_dir, version="0.3.0")
    rows = status(tmp_project, skills_dir, "0.4.0")
    assert any(s.state == STALE for s in rows)
    _run(tmp_project, skills_dir, version="0.4.0")
    assert all(s.state == CURRENT for s in status(tmp_project, skills_dir, "0.4.0"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH="$(pwd)/lib" .venv/bin/python3 -m pytest tests/skills/test_sync.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'skills.sync'`

- [ ] **Step 3: Write minimal implementation**

```python
# lib/skills/sync.py
from __future__ import annotations

import shutil
from dataclasses import dataclass, asdict
from pathlib import Path

from skills import ABSENT, CURRENT, STALE, CONFLICTED, ORPHANED, UNSUPPORTED
from skills.catalog import load_catalog
from skills.targets import SURFACES, detect_surfaces, dest_dir
from skills.project import render
from skills.manifest import (
    hash_disk, load_manifest, save_manifest, classify_skill, hash_bytes,
)


@dataclass
class SkillState:
    surface: str
    skill: str
    state: str
    action: str = ""


def _classify_all(project_root, skills_dir, catalog_version, surfaces):
    pkgs = load_catalog(skills_dir)
    by_name = {p.name: p for p in pkgs}
    manifest = load_manifest(project_root)
    rows: list[SkillState] = []
    plans = []  # (surface, skill, state, rendered_or_None, dest)
    for surface in surfaces:
        surf_entry = manifest.get("surfaces", {}).get(surface.id, {}).get("skills", {})
        seen = set()
        for name, pkg in by_name.items():
            seen.add(name)
            rendered = render(pkg, surface, catalog_version)
            dest = dest_dir(surface, name, project_root)
            state = classify_skill(rendered, hash_disk(dest), surf_entry.get(name))
            rows.append(SkillState(surface.id, name, state))
            plans.append((surface, name, state, rendered, dest))
        for name, entry in surf_entry.items():
            if name in seen:
                continue
            dest = dest_dir(surface, name, project_root)
            state = classify_skill(None, hash_disk(dest), entry)
            if not dest.exists():
                continue
            rows.append(SkillState(surface.id, name, state))
            plans.append((surface, name, state, None, dest))
    return rows, plans, manifest, by_name


def status(project_root, skills_dir, catalog_version, *, only_surface=None):
    surfaces = [s for s in detect_surfaces(Path(project_root))
                if only_surface in (None, s.id)]
    if not surfaces:
        return [SkillState(s.id, "*", UNSUPPORTED) for s in SURFACES
                if only_surface in (None, s.id)]
    rows, _, _, _ = _classify_all(Path(project_root), Path(skills_dir),
                                  catalog_version, surfaces)
    return rows


def sync(project_root, skills_dir, catalog_version, *, force=False, only_surface=None):
    project_root = Path(project_root)
    skills_dir = Path(skills_dir)
    surfaces = [s for s in detect_surfaces(project_root) if only_surface in (None, s.id)]
    if not surfaces:
        return [SkillState(s.id, "*", UNSUPPORTED) for s in SURFACES
                if only_surface in (None, s.id)]
    rows, plans, manifest, _ = _classify_all(project_root, skills_dir,
                                             catalog_version, surfaces)
    manifest.setdefault("surfaces", {})
    for surface, name, state, rendered, dest in plans:
        surf = manifest["surfaces"].setdefault(surface.id, {"root": surface.skills_root,
                                                            "skills": {}})
        if state == ORPHANED or (rendered is None and force and state == CONFLICTED):
            if dest.exists():
                shutil.rmtree(dest)
            surf["skills"].pop(name, None)
        elif state in (ABSENT, STALE) or (state == CONFLICTED and force):
            if dest.exists():
                shutil.rmtree(dest)
            for rel, content in rendered.items():
                target = dest / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            surf["skills"][name] = {
                "files": {rel: hash_bytes(content) for rel, content in rendered.items()},
                "projected_at_version": catalog_version,
            }
    manifest["catalog_version"] = catalog_version
    save_manifest(project_root, manifest)
    return rows
```

```python
# lib/skills/__main__.py
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from skills import CURRENT, CONFLICTED, UNSUPPORTED
from skills.sync import sync, status


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(prog="skills")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("sync", "status"):
        sp = sub.add_parser(name)
        sp.add_argument("--project-root", required=True)
        sp.add_argument("--skills-dir", required=True)
        sp.add_argument("--catalog-version", default="dev")
        sp.add_argument("--surface", default=None)
        sp.add_argument("--json", action="store_true")
        if name == "sync":
            sp.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    try:
        if args.cmd == "sync":
            rows = sync(args.project_root, args.skills_dir, args.catalog_version,
                        force=args.force, only_surface=args.surface)
        else:
            rows = status(args.project_root, args.skills_dir, args.catalog_version,
                          only_surface=args.surface)
    except Exception as exc:  # config/catalog error
        print(f"error: {exc}", file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps([asdict(r) for r in rows], indent=2))
    else:
        _print_table(args, rows)

    if args.cmd == "sync":
        return 2 if any(r.state == CONFLICTED for r in rows) else 0
    return 0 if all(r.state in (CURRENT, UNSUPPORTED) for r in rows) else 1


def _print_table(args, rows):
    print(f"catalog {args.catalog_version} · {len(rows)} row(s)")
    for r in rows:
        line = f"  {r.surface:<12} {r.skill:<20} {r.state}"
        if r.action:
            line += f"  ({r.action})"
        print(line)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH="$(pwd)/lib" .venv/bin/python3 -m pytest tests/skills/test_sync.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add lib/skills/sync.py lib/skills/__main__.py tests/skills/test_sync.py
git commit -m "feat(skills): sync/status orchestration and python CLI"
```

---

### Task 8: Bash wrapper, dispatch, init hook, first package

**Files:**
- Create: `lib/cmd/skills.sh`
- Create: `skills/workbench-draft/SKILL.md`
- Modify: `speed` (add `skills)` case near line 308, before `self-uninstall)`)
- Modify: `lib/cmd/project.sh` (append a projection step to `cmd_init`)
- Test: `tests/skills/test_cli_e2e.py`

**Interfaces:**
- Consumes: `python -m skills` (Task 7)
- Produces: `cmd_skills` bash function; a real `speed skills sync|status` path; `speed init` that projects detected surfaces.

- [ ] **Step 1: Write the failing test**

```python
# tests/skills/test_cli_e2e.py
import subprocess, sys, os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PY = REPO / ".venv" / "bin" / "python3"

def _skills(project, *args):
    env = dict(os.environ, PYTHONPATH=str(REPO / "lib"))
    return subprocess.run(
        [str(PY), "-m", "skills", *args,
         "--project-root", str(project),
         "--skills-dir", str(REPO / "skills"),
         "--catalog-version", "test"],
        capture_output=True, text=True, env=env,
    )

def test_end_to_end_projects_real_workbench_draft(tmp_path):
    project = tmp_path / "proj"
    (project / ".claude").mkdir(parents=True)
    r = _skills(project, "sync")
    assert r.returncode == 0, r.stderr
    projected = project / ".claude" / "skills" / "workbench-draft" / "SKILL.md"
    assert projected.exists()
    text = projected.read_text()
    assert "x-speed-managed: true" in text
    # status is clean afterward
    s = _skills(project, "status")
    assert s.returncode == 0, s.stderr
    assert "current" in s.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH="$(pwd)/lib" .venv/bin/python3 -m pytest tests/skills/test_cli_e2e.py -v`
Expected: FAIL — `skills/workbench-draft/SKILL.md` does not exist yet (assert on `projected.exists()` fails)

- [ ] **Step 3: Write the canonical package + bash wrapper + wiring**

Create `skills/workbench-draft/SKILL.md` (minimal valid Phase-1 package; full interview body arrives with 03-guided-authoring):

```markdown
---
name: workbench-draft
description: >
  Run a guided PRD, design, RFC, or evaluation interview and draft the matching
  SPEED spec from the answers, then self-review it. Use when asked to "draft a
  spec", "run the interview", or "start a PRD/design/RFC".
---

# workbench-draft

Guide the author through a structured interview and produce a reviewable SPEED
spec. This Phase-1 package establishes the skill contract; the full question
banks are delivered with the guided-authoring workflow.

## When to invoke
- The user asks to draft or spec a PRD, design, RFC, or evaluation.

## When NOT to invoke
- Implementation, debugging, or review tasks — those are other skills.

## Workflow
1. Determine the artifact type (prd | design | rfc | eval) and feature name.
2. Interview the author one question at a time, carrying prior answers forward.
3. Draft the spec from the matching SPEED template.
4. Self-review for placeholders, contradictions, and scope creep before handoff.

## Output
- A drafted spec in the correct `specs/` location, ready for human review.

## Completion gate
- The draft fills every required template section; unresolved items are listed
  explicitly as open questions rather than left blank.
```

Create `lib/cmd/skills.sh`:

```bash
#!/usr/bin/env bash
# skills.sh — project and inspect the SPEED canonical skill catalog

_skills_python() {
    if [[ -n "${SPEED_PYTHON:-}" ]]; then echo "$SPEED_PYTHON"
    elif [[ -x "${SPEED_DIR}/.venv/bin/python3" ]]; then echo "${SPEED_DIR}/.venv/bin/python3"
    elif [[ -x "${PROJECT_ROOT}/.venv/bin/python3" ]]; then echo "${PROJECT_ROOT}/.venv/bin/python3"
    else echo "python3"; fi
}

_skills_catalog_version() {
    local v
    v=$(jq -r '.version // empty' "${SPEED_HOME:-$HOME/.speed}/receipt.json" 2>/dev/null)
    [[ -z "$v" ]] && v="dev"
    echo "$v"
}

cmd_skills() {
    local sub="${1:-status}"; shift || true
    case "$sub" in
        sync|status|doctor) ;;
        *) log_error "Unknown skills subcommand: ${sub}"; return 1 ;;
    esac
    if [[ "$sub" == "doctor" ]]; then
        # Phase 2 delivers doctor; for now alias to status for a usable view.
        sub="status"
    fi
    PYTHONPATH="${SPEED_DIR}/lib" "$(_skills_python)" -m skills "$sub" \
        --project-root "${PROJECT_ROOT}" \
        --skills-dir "${SPEED_DIR}/skills" \
        --catalog-version "$(_skills_catalog_version)" \
        "$@"
}
```

Modify `speed` — add the case (place it immediately before the `self-uninstall)` line, around line 308):

```bash
        skills)    cmd_skills "$@" ;;
```

Modify `lib/cmd/project.sh` — append a projection step inside `cmd_init`, after the final existing numbered step and before its closing success log:

```bash
    # N. Project the built-in skill catalog into detected agent surfaces
    if [[ -d "${SPEED_DIR}/skills" ]]; then
        if cmd_skills sync >/dev/null 2>&1; then
            log_success "Skills projected into detected agent surfaces"
        else
            log_info "Skill projection skipped (no supported surface or conflicts) — run: speed skills status"
        fi
    fi
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH="$(pwd)/lib" .venv/bin/python3 -m pytest tests/skills/test_cli_e2e.py -v`
Expected: PASS (1 test)

Then the full suite:
Run: `PYTHONPATH="$(pwd)/lib" .venv/bin/python3 -m pytest tests/skills/ -v`
Expected: PASS (all tests, 0 failures)

Then a live smoke test with the real CLI against a scratch project:
```bash
tmp=$(mktemp -d); mkdir -p "$tmp/.claude"
SPEED_PROJECT_ROOT="$tmp" ./speed skills sync
SPEED_PROJECT_ROOT="$tmp" ./speed skills status
ls "$tmp/.claude/skills/workbench-draft/"
```
Expected: `SKILL.md` present with provenance keys; status shows `current`.

- [ ] **Step 5: Commit**

```bash
git add speed lib/cmd/skills.sh lib/cmd/project.sh skills/workbench-draft/SKILL.md tests/skills/test_cli_e2e.py
git commit -m "feat(skills): speed skills CLI, init projection hook, workbench-draft package"
```

---

## Self-Review

**Spec coverage** (RFC sections → tasks):
- Canonical package + validation contract → Tasks 2, 3, 8 (real package).
- Projection format + provenance + determinism → Task 5.
- Manifest / managed-file identity / six states → Task 6.
- `speed skills sync|status` + exit codes + init hook → Tasks 7, 8.
- Claude-first surface, Codex deferred → Task 4 (`SURFACES` list) + Global Constraints.
- `doctor` → deferred to Phase 2, aliased to `status` in Task 8 so the verb exists without overpromising.
- `speed draft` launcher, Codex adapter, provenance record → out of Phase 1 (RFC Phases 3–4).

**Placeholder scan:** every code step carries real code; the only intentional minimal artifact is the `workbench-draft` body, explicitly owned by 03-guided-authoring and marked as such.

**Type consistency:** `SkillPackage(name, root, meta, body, files)`, `Surface(id, skills_root, marker)`, `Violation(package, path, reason)`, `SkillState(surface, skill, state, action)`, and `classify_skill(rendered, disk, entry)` are used with identical signatures across Tasks 2–8. State constants come from `skills/__init__` in both `manifest.py` and `sync.py`.

## Deferred to later phases (not this plan)
- Phase 2: real `doctor` with one-repair-path output; rename/forwarding; rollback-on-downgrade hardening.
- Phase 3: Codex `.agents/skills/` adapter (append one `Surface` + detection).
- Phase 4: `speed draft` agent-launch routing; workflow provenance record (SK-S9).
