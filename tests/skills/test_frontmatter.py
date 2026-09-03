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


UNTERMINATED = """---
name: example-skill
description: someone deleted the closing fence

# example-skill
Body line.
"""


def test_parse_reports_an_unterminated_fence_instead_of_ignoring_it():
    """An opened block that never closes is a syntax error, not 'no front matter'."""
    with pytest.raises(ValueError, match="front matter"):
        parse(UNTERMINATED)


def test_inject_refuses_to_add_a_second_block_to_broken_front_matter():
    with pytest.raises(ValueError, match="front matter"):
        inject(UNTERMINATED, {"x-workbench-managed": "true"})


def test_a_fence_that_is_only_a_body_horizontal_rule_is_not_front_matter():
    """A rule further down the file must not be read as an opening fence."""
    text = "# doc\n\n---\n\nmore body\n"
    meta, body = parse(text)
    assert meta == {}
    assert body == text


def test_a_duplicate_key_is_reported_not_silently_overwritten():
    """Keeping the last value discards the first with nothing said about it."""
    text = "---\nname: first\nname: second\ndescription: d\n---\n\nBody.\n"

    with pytest.raises(ValueError, match="duplicate key 'name'"):
        parse(text)
