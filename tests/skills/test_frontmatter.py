import pytest

from skills.frontmatter import inject, parse

SAMPLE = """---
name: example-skill
description: >
  Run a guided interview
  and draft a spec.
---

# example-skill
Body line.
"""

STRUCTURED = """---
name: example-skill
description: >
  Use when: the user asks about charts.
allowed-tools:
  - Read
  - Bash(git status:*)
metadata:
  owner: platform
  tier: 2
license: "MIT: see LICENSE"
---

# example-skill
Body line.
"""


def test_parse_extracts_scalar_and_folded():
    meta, body = parse(SAMPLE)
    assert meta["name"] == "example-skill"
    assert meta["description"] == "Run a guided interview and draft a spec."
    assert body.startswith("# example-skill")


def test_parse_no_frontmatter_returns_empty_meta():
    meta, body = parse("# just a doc\n")
    assert meta == {}
    assert body == "# just a doc\n"


def test_parse_does_not_invent_keys_for_structures_it_cannot_model():
    meta, _ = parse(STRUCTURED)
    assert meta["name"] == "example-skill"
    assert meta["license"] == '"MIT: see LICENSE"'
    assert not any(key.startswith("-") for key in meta)
    assert "owner" not in meta


def test_inject_appends_keys_and_leaves_the_rest_byte_identical():
    out = inject(STRUCTURED, {"x-workbench-managed": "true"})
    for line in STRUCTURED.splitlines():
        assert line in out.splitlines()
    assert "x-workbench-managed: true" in out
    assert out.index("x-workbench-managed") < out.index("---\n\n# example-skill")


def test_inject_replaces_its_own_keys_instead_of_duplicating_them():
    once = inject(SAMPLE, {"x-workbench-managed": "true", "x-workbench-source": "a"})
    twice = inject(once, {"x-workbench-managed": "true", "x-workbench-source": "a"})
    assert twice == once


def test_inject_creates_a_block_when_there_is_no_front_matter():
    out = inject("# just a doc\n", {"x-workbench-managed": "true"})
    meta, body = parse(out)
    assert meta == {"x-workbench-managed": "true"}
    assert body == "# just a doc\n"


def test_inject_is_deterministic():
    extra = {"x-workbench-managed": "true"}
    assert inject(STRUCTURED, extra) == inject(STRUCTURED, extra)


@pytest.mark.parametrize("source", [SAMPLE, STRUCTURED])
def test_injected_front_matter_still_loads_as_yaml(source):
    yaml = pytest.importorskip("yaml")
    out = inject(source, {"x-workbench-managed": "true", "x-workbench-source": "s"})
    loaded = yaml.safe_load(out.split("---\n")[1])
    assert loaded["name"] == "example-skill"
    assert loaded["x-workbench-source"] == "s"
