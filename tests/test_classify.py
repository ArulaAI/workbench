#!/usr/bin/env python3
"""Tests for prototype-based text classifier (lib/learn/classify.py).

Tests prototype TF-IDF matching, sklearn integration, training,
category coverage, prototype loading, and regression guard.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from lib.learn.classify import (
    classify,
    train_classifier,
    ClassifyResult,
    REVIEW_PROTOTYPES,
    _load_prototypes,
    _sklearn_available,
)

passed = 0
failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name} — {detail}")


# ══════════════════════════════════════════════════════════════
# 1: Prototype Loading
# ══════════════════════════════════════════════════════════════

print("\n=== 1: Prototype Loading ===")

# Missing file raises FileNotFoundError
try:
    _load_prototypes(Path("/nonexistent/file.jsonl"))
    check("Missing file raises FileNotFoundError", False, "no exception")
except FileNotFoundError:
    check("Missing file raises FileNotFoundError", True)
except Exception as e:
    check("Missing file raises FileNotFoundError", False, f"got {type(e).__name__}")

# Empty file raises ValueError
with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
    f.write("\n\n")
    empty_path = f.name
try:
    _load_prototypes(Path(empty_path))
    check("Empty file raises ValueError", False, "no exception")
except ValueError:
    check("Empty file raises ValueError", True)
except Exception as e:
    check("Empty file raises ValueError", False, f"got {type(e).__name__}")
finally:
    os.unlink(empty_path)

# Valid JSONL loads correctly
with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
    f.write('{"category": "test_cat", "text": "example one"}\n')
    f.write('{"category": "test_cat", "text": "example two"}\n')
    f.write('{"category": "other_cat", "text": "example three"}\n')
    valid_path = f.name
try:
    protos = _load_prototypes(Path(valid_path))
    check("Valid JSONL loads 2 categories",
          len(protos) == 2, f"got {len(protos)}")
    check("test_cat has 2 examples",
          len(protos.get("test_cat", [])) == 2,
          f"got {len(protos.get('test_cat', []))}")
    check("other_cat has 1 example",
          len(protos.get("other_cat", [])) == 1)
finally:
    os.unlink(valid_path)


# ══════════════════════════════════════════════════════════════
# 2: Category Coverage
# ══════════════════════════════════════════════════════════════

print("\n=== 2: Category Coverage ===")

check("REVIEW_PROTOTYPES has 7 categories",
      len(REVIEW_PROTOTYPES) == 7, f"got {len(REVIEW_PROTOTYPES)}")

expected_cats = {"convention", "correctness", "scope", "testing",
                 "maintainability", "performance", "spec_alignment"}
actual_cats = set(REVIEW_PROTOTYPES.keys())
check("All expected categories present",
      actual_cats == expected_cats, f"got {actual_cats}")

for cat, examples in REVIEW_PROTOTYPES.items():
    check(f"{cat} has prototype sentences",
          len(examples) > 0, f"got {len(examples)}")


# ══════════════════════════════════════════════════════════════
# 3: Classification Per Category
# ══════════════════════════════════════════════════════════════

print("\n=== 3: Classification Per Category ===")

if _sklearn_available:
    r1 = classify(
        "Function silently fails on invalid input and returns empty result. "
        "Error is silently ignored with bare except.",
        REVIEW_PROTOTYPES,
    )
    check("silently fails + bare except → correctness",
          r1.category == "correctness", f"got {r1.category}")

    r2 = classify(
        "Should use the project wrapper lib/api/client.py:fetch() "
        "instead of raw httpx.",
        REVIEW_PROTOTYPES,
    )
    check("wrapper + project → convention",
          r2.category == "convention", f"got {r2.category}")

    r3 = classify(
        "No test for the edge case where section is missing. "
        "Add parametrize with missing section input.",
        REVIEW_PROTOTYPES,
    )
    check("no test + edge case → testing",
          r3.category == "testing", f"got {r3.category}")

    r4 = classify(
        "This loop is O(n^2) and will be a bottleneck on large inputs. "
        "Consider using a set for O(1) lookups.",
        REVIEW_PROTOTYPES,
    )
    check("O(n^2) + bottleneck → performance",
          r4.category == "performance", f"got {r4.category}")

    r5 = classify(
        "implementation does not match spec-defined template structure",
        REVIEW_PROTOTYPES,
    )
    check("spec template → spec_alignment",
          r5.category == "spec_alignment", f"got {r5.category}")

    r6 = classify(
        "reformatted lines unrelated to this task",
        REVIEW_PROTOTYPES,
    )
    check("unrelated lines → scope",
          r6.category == "scope", f"got {r6.category}")

    r7 = classify(
        "dead code stub left over from previous implementation with no callers",
        REVIEW_PROTOTYPES,
    )
    check("dead code + no callers → maintainability",
          r7.category == "maintainability", f"got {r7.category}")
else:
    print("  SKIP: sklearn not available, classification tests skipped")


# ══════════════════════════════════════════════════════════════
# 4: Classification Metadata
# ══════════════════════════════════════════════════════════════

print("\n=== 4: Classification Metadata ===")

if _sklearn_available:
    r = classify(
        "Function silently fails on invalid input",
        REVIEW_PROTOTYPES,
    )
    check("Stage is prototype or prototype_embed",
          r.stage in ("prototype", "prototype_embed"), f"got {r.stage}")
    check("Confidence > 0",
          r.confidence > 0, f"got {r.confidence}")
    check("Scores dict has all categories",
          set(r.scores.keys()) == expected_cats,
          f"got {set(r.scores.keys())}")
else:
    print("  SKIP: sklearn not available")


# ══════════════════════════════════════════════════════════════
# 5: sklearn Stage
# ══════════════════════════════════════════════════════════════

print("\n=== 5: sklearn Stage ===")

r_no_model = classify(
    "ambiguous text",
    REVIEW_PROTOTYPES,
    model_path=Path("/nonexistent/model.pkl"),
)
check("Missing model file: sklearn skipped",
      r_no_model.stage != "sklearn")

r_none_model = classify(
    "ambiguous text",
    REVIEW_PROTOTYPES,
    model_path=None,
)
check("None model_path: sklearn skipped",
      r_none_model.stage != "sklearn")


# ══════════════════════════════════════════════════════════════
# 6: train_classifier
# ══════════════════════════════════════════════════════════════

print("\n=== 6: train_classifier ===")

with tempfile.TemporaryDirectory() as tmpdir:
    obs_dir = Path(tmpdir) / "observations"
    obs_dir.mkdir()
    model_path = Path(tmpdir) / "models" / "review_classifier.pkl"

    # Not enough data: returns False
    result = train_classifier(obs_dir, model_path, min_samples=200)
    check("< 200 samples returns False", result is False)
    check("No model file created", not model_path.exists())

    # Write enough labeled observations
    jsonl_path = obs_dir / "training.jsonl"
    lines = []
    categories = ["correctness", "convention", "testing", "maintainability",
                  "scope", "performance", "spec_alignment"]
    for i in range(250):
        cat = categories[i % len(categories)]
        obs = {
            "id": f"sha256:{'a' * 64}",
            "feature": "train-feat",
            "stage": "reviewer",
            "task_id": str(i),
            "timestamp": "2026-03-01T00:00:00Z",
            "observation_type": "reviewer_finding",
            "detail": {
                "category": cat,
                "finding": f"This is a {cat} finding number {i} with some unique text {i*7}",
            },
            "weight": 1.5,
        }
        lines.append(json.dumps(obs))
    jsonl_path.write_text("\n".join(lines) + "\n")

    try:
        result = train_classifier(obs_dir, model_path, min_samples=200)
        if _sklearn_available:
            check(">= 200 samples returns True (sklearn available)",
                  result is True)
            check("Model file created", model_path.exists())

            if model_path.exists():
                r_trained = classify(
                    "This is a correctness bug crash AttributeError",
                    REVIEW_PROTOTYPES,
                    model_path=model_path,
                )
                check("Trained model is usable by classify()",
                      r_trained.stage in ("prototype", "prototype_embed", "sklearn"),
                      f"got stage={r_trained.stage}")
        else:
            check(">= 200 samples returns False (sklearn not available)",
                  result is False)
            check("No model file (sklearn not available)",
                  not model_path.exists())
    except Exception as e:
        check("train_classifier runs without error", False, str(e))

    # Non-existent observations dir
    result_empty = train_classifier(
        Path("/nonexistent/dir"), model_path, min_samples=200
    )
    check("Non-existent dir returns False", result_empty is False)


# ══════════════════════════════════════════════════════════════
# 7: Regression Guard
# ══════════════════════════════════════════════════════════════

print("\n=== 7: Regression Guard ===")

held_out_dir = Path(PROJECT_ROOT) / ".speed" / "features" / "speed-security" / "logs"
if held_out_dir.exists() and _sklearn_available:
    EXPECTED = {
        ("review-1.json", 0): "scope",
        ("review-10.json", 0): "convention",
        ("review-10.json", 1): "spec_alignment",
        ("review-10.json", 2): "spec_alignment",
        ("review-10.json", 3): "correctness",
        ("review-11.json", 0): "maintainability",
        ("review-11.json", 1): "testing",
        ("review-11.json", 2): "correctness",
        ("review-12.json", 0): "correctness",
        ("review-12.json", 1): "correctness",
        ("review-12.json", 2): "testing",
        ("review-12.json", 3): "correctness",
        ("review-12.json", 4): "maintainability",
        ("review-2.json", 0): "correctness",
        ("review-2.json", 1): "correctness",
        ("review-2.json", 2): "correctness",
        ("review-2.json", 3): "correctness",
        ("review-2.json", 4): "maintainability",
        ("review-3.json", 0): "correctness",
        ("review-3.json", 1): "correctness",
        ("review-3.json", 2): "testing",
        ("review-3.json", 3): "testing",
        ("review-4.json", 0): "correctness",
        ("review-4.json", 1): "performance",
        ("review-4.json", 2): "maintainability",
        ("review-4.json", 3): "maintainability",
        ("review-5.json", 0): "spec_alignment",
        ("review-5.json", 1): "spec_alignment",
        ("review-6.json", 0): "maintainability",
        ("review-6.json", 1): "correctness",
        ("review-6.json", 2): "testing",
        ("review-6.json", 3): "testing",
        ("review-7.json", 0): "maintainability",
        ("review-7.json", 1): "maintainability",
        ("review-8.json", 0): "correctness",
        ("review-8.json", 1): "scope",
        ("review-8.json", 2): "correctness",
        ("review-9.json", 0): "spec_alignment",
        ("review-9.json", 1): "correctness",
        ("review-9.json", 2): "spec_alignment",
        ("review-9.json", 3): "performance",
    }

    findings = []
    for f in sorted(held_out_dir.glob("review-*.json")):
        try:
            text = f.read_text()
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
                data = json.loads(lines[-1]) if lines else None
            if not isinstance(data, dict):
                continue
            for i, issue in enumerate(data.get("issues", [])):
                if not isinstance(issue, dict):
                    continue
                msg = issue.get("message", "").strip()
                if msg:
                    findings.append({"key": (f.name, i), "message": msg})
        except (json.JSONDecodeError, OSError):
            continue

    correct = 0
    total_labeled = 0
    for f in findings:
        expected = EXPECTED.get(f["key"])
        if not expected:
            continue
        total_labeled += 1
        cr = classify(f["message"], REVIEW_PROTOTYPES)
        if cr.category == expected:
            correct += 1

    if total_labeled > 0:
        accuracy = correct / total_labeled
        check(f"Held-out accuracy >= 90% ({correct}/{total_labeled} = {accuracy:.0%})",
              accuracy >= 0.90, f"got {accuracy:.0%}")
    else:
        print("  SKIP: No labeled findings found in held-out data")
else:
    print("  SKIP: Held-out data not available or sklearn not installed")


# ══════════════════════════════════════════════════════════════
# Results
# ══════════════════════════════════════════════════════════════

print(f"\n{'='*60}")
print(f"Results: {passed} passed, {failed} failed")
if failed:
    sys.exit(1)
