from skills.frontmatter import parse, serialize

SAMPLE = """---
name: example-skill
description: >
  Run a guided interview
  and draft a spec.
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


def test_serialize_roundtrip_is_stable():
    meta = {"name": "x", "description": "one two"}
    out = serialize(meta, "# Body\n")
    meta2, body2 = parse(out)
    assert meta2 == meta
    assert body2.strip() == "# Body"
    assert serialize(meta, "# Body\n") == out  # deterministic
