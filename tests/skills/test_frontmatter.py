import pytest
import yaml

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
    # A folded block scalar clips to a single trailing newline, per YAML.
    assert meta["description"] == "Run a guided interview and draft a spec.\n"
    assert body.startswith("# example-skill")


def test_parse_no_frontmatter_returns_empty_meta():
    meta, body = parse("# just a doc\n")
    assert meta == {}
    assert body == "# just a doc\n"


def test_parse_reads_the_structures_yaml_defines():
    """Sequences, nested mappings and quoted scalars are the library's job."""
    meta, _ = parse(STRUCTURED)

    assert meta["allowed-tools"] == ["Read", "Bash(git status:*)"]
    assert meta["metadata"] == {"owner": "platform", "tier": 2}
    # The quotes delimit the value; they are not part of it.
    assert meta["license"] == "MIT: see LICENSE"


def test_a_quoted_name_is_the_same_name():
    """The old parser kept the quotes and called the package name a mismatch."""
    meta, _ = parse('---\nname: "demo"\ndescription: \'d\'\n---\n\nBody.\n')

    assert meta["name"] == "demo"
    assert meta["description"] == "d"


def test_a_comment_is_not_a_key():
    meta, _ = parse("---\n# note: not a key\nname: demo\n---\n\nBody.\n")

    assert meta == {"name": "demo"}


def test_scalars_keep_the_type_yaml_gives_them():
    meta, _ = parse("---\ncount: 2\nratio: 1.5\nenabled: true\nempty:\n---\n\nB.\n")

    assert meta["count"] == 2
    assert meta["ratio"] == 1.5
    assert meta["enabled"] is True
    assert meta["empty"] is None


def test_an_escape_inside_a_double_quoted_scalar_is_applied():
    meta, _ = parse('---\ndescription: "line\\nbreak"\n---\n\nBody.\n')

    assert meta["description"] == "line\nbreak"


def test_an_empty_block_is_an_empty_mapping_not_an_error():
    for block in ("---\n---\n\nBody.\n", "---\n# only a comment\n---\n\nBody.\n"):
        meta, body = parse(block)
        assert meta == {}
        assert body == "Body.\n"


def test_a_block_that_is_not_a_mapping_is_rejected():
    """A sequence or a bare scalar cannot carry skill metadata."""
    with pytest.raises(ValueError, match="expected a mapping"):
        parse("---\n- Read\n- Write\n---\n\nBody.\n")

    with pytest.raises(ValueError, match="expected a mapping"):
        parse("---\njust a string\n---\n\nBody.\n")


def test_a_non_string_key_is_rejected():
    with pytest.raises(ValueError, match="not a string"):
        parse("---\n1: one\n---\n\nBody.\n")


def test_invalid_yaml_is_reported_as_a_front_matter_error():
    with pytest.raises(ValueError, match="malformed front matter"):
        parse("---\nname: [unclosed\n---\n\nBody.\n")


def test_inject_appends_keys_and_leaves_the_rest_byte_identical():
    out = inject(STRUCTURED, {"x-workbench-managed": True})
    for line in STRUCTURED.splitlines():
        assert line in out.splitlines()
    assert "x-workbench-managed: true" in out
    assert out.index("x-workbench-managed") < out.index("---\n\n# example-skill")


def test_inject_replaces_its_own_keys_instead_of_duplicating_them():
    once = inject(SAMPLE, {"x-workbench-managed": True, "x-workbench-source": "a"})
    twice = inject(once, {"x-workbench-managed": True, "x-workbench-source": "a"})
    assert twice == once


def test_inject_creates_a_block_when_there_is_no_front_matter():
    out = inject("# just a doc\n", {"x-workbench-managed": True})
    meta, body = parse(out)
    assert meta == {"x-workbench-managed": True}
    assert body == "# just a doc\n"


def test_inject_is_deterministic():
    extra = {"x-workbench-managed": True}
    assert inject(STRUCTURED, extra) == inject(STRUCTURED, extra)


@pytest.mark.parametrize("source", [SAMPLE, STRUCTURED])
def test_injected_front_matter_still_loads_as_yaml(source):
    out = inject(source, {"x-workbench-managed": True, "x-workbench-source": "s"})
    loaded = yaml.safe_load(out.split("---\n")[1])
    assert loaded["name"] == "example-skill"
    assert loaded["x-workbench-source"] == "s"


@pytest.mark.parametrize("name", ["true", "on", "no", "null", "y"])
def test_a_skill_name_that_reads_as_a_boolean_is_quoted(name):
    """Unquoted, `x-workbench-source: on` comes back as True, not as a name."""
    out = inject(SAMPLE, {"x-workbench-source": name})

    assert parse(out)[0]["x-workbench-source"] == name


def test_inject_keeps_the_line_endings_the_document_already_uses():
    crlf = "---\r\nname: example-skill\r\n---\r\n\r\nBody.\r\n"
    out = inject(crlf, {"x-workbench-managed": True})

    assert "x-workbench-managed: true\r\n" in out
    assert "\n" not in out.replace("\r\n", "")
    assert parse(out)[0]["name"] == "example-skill"


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
        inject(UNTERMINATED, {"x-workbench-managed": True})


def test_a_fence_that_is_only_a_body_horizontal_rule_is_not_front_matter():
    """A rule further down the file must not be read as an opening fence."""
    text = "# doc\n\n---\n\nmore body\n"
    meta, body = parse(text)
    assert meta == {}
    assert body == text


def test_a_duplicate_key_is_reported_not_silently_overwritten():
    """YAML keeps the last value; discarding the first says nothing about it."""
    text = "---\nname: first\nname: second\ndescription: d\n---\n\nBody.\n"

    with pytest.raises(ValueError, match="duplicate key 'name'"):
        parse(text)


def test_inject_without_front_matter_drops_one_blank_line_not_all_of_them():
    """`opening` already ends with a blank line, so one leading break is
    redundant and gets removed. `lstrip("\\r\\n")` removed the whole run,
    silently rewriting a body the function promises to copy verbatim."""
    out = inject("\n\n\n# Title\n", {"x-workbench-managed": True})

    assert out.endswith("---\n\n\n\n# Title\n")
    meta, body = parse(out)
    assert meta == {"x-workbench-managed": True}
    assert body == "\n\n# Title\n"


def test_inject_counts_crlf_as_a_single_break():
    out = inject("\r\n\r\n# Title\n", {"x-workbench-managed": True})

    assert out.endswith("---\r\n\r\n\r\n# Title\n")
