"""Prototype-based text classifier for observation extraction.

Stage progression: prototype (TF-IDF + optional embedding cascade)
→ sklearn (if trained) → fallback.

Prototypes are short behavior-description sentences grouped by category.
Classification is cosine similarity between a TF-IDF-vectorized finding
and the prototype matrix. No API calls, no keyword lists.

Current consumers:
  - Step 2 (review findings): 7 categories, see REVIEW_PROTOTYPES
"""

import json as _json
import os
from dataclasses import dataclass
from pathlib import Path

# sklearn is optional — Stage 2 degrades gracefully if unavailable
_sklearn_available = False
try:
    import joblib
    from sklearn.pipeline import Pipeline as SkPipeline
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import SGDClassifier
    from sklearn.model_selection import train_test_split
    _sklearn_available = True
except ImportError:
    pass

# Cached sklearn model (loaded once per process)
_cached_model = None
_cached_model_path = None


@dataclass
class ClassifyResult:
    """Output of classify()."""

    category: str       # winning category name, or "unclassified"
    stage: str          # "prototype" | "prototype_embed" | "sklearn" | "fallback"
    confidence: float   # prototype: cosine similarity. sklearn: predict_proba. fallback: 0.0
    scores: dict[str, float]  # per-category max similarity


# ── Prototype loading ────────────────────────────────────────────────

def _load_prototypes(path: Path) -> dict[str, list[str]]:
    """Load prototypes from .jsonl file.

    Each line: {"category": "correctness", "text": "injection via ..."}
    Returns dict mapping category name to list of prototype sentences.
    Raises FileNotFoundError if file is missing, ValueError if empty.
    """
    result: dict[str, list[str]] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = _json.loads(line)
            result.setdefault(obj["category"], []).append(obj["text"])
    if not result:
        raise ValueError(f"Empty prototype file: {path}")
    return result


# ── Cached TF-IDF index (computed once per process) ──────────────────

_proto_vectorizer = None
_proto_matrix = None
_proto_labels: list[str] = []


def _ensure_prototype_index(prototypes: dict[str, list[str]]) -> tuple:
    """Build or return cached TF-IDF index over prototype sentences."""
    global _proto_vectorizer, _proto_matrix, _proto_labels
    if _proto_vectorizer is not None:
        return _proto_vectorizer, _proto_matrix, _proto_labels

    texts: list[str] = []
    labels: list[str] = []
    for cat, examples in prototypes.items():
        for ex in examples:
            texts.append(ex)
            labels.append(cat)

    vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=1, max_features=5000, sublinear_tf=True)
    matrix = vectorizer.fit_transform(texts)

    _proto_vectorizer = vectorizer
    _proto_matrix = matrix
    _proto_labels = labels
    return vectorizer, matrix, labels


# ── Embedding cascade (optional, loaded lazily) ──────────────────────

_embed_model = None
_embed_proto_matrix = None


def _ensure_embed_index(prototypes: dict[str, list[str]]) -> tuple:
    """Build or return cached embedding index. Returns (None, None, labels) if fastembed unavailable."""
    global _embed_model, _embed_proto_matrix, _proto_labels
    if _embed_model is not None and _embed_proto_matrix is not None:
        return _embed_model, _embed_proto_matrix, _proto_labels

    try:
        from fastembed import TextEmbedding
        import numpy as np
    except ImportError:
        return None, None, _proto_labels

    if not _proto_labels:
        _ensure_prototype_index(prototypes)

    texts = []
    for examples in prototypes.values():
        texts.extend(examples)

    model = TextEmbedding("BAAI/bge-small-en-v1.5")
    embeddings = np.array(list(model.embed(texts)))

    _embed_model = model
    _embed_proto_matrix = embeddings
    return model, embeddings, _proto_labels


# ── Classifier ───────────────────────────────────────────────────────

def classify(text: str,
             prototypes: dict[str, list[str]],
             model_path: Path | None = None,
             min_similarity: float = 0.08,
             cascade_threshold: float = 0.20) -> ClassifyResult:
    """Classify free text into one of the prototype categories.

    Stage 1 (prototype): TF-IDF cosine similarity against prototype
    sentences. If best similarity >= cascade_threshold, return. If
    between min_similarity and cascade_threshold and fastembed is
    available, cascade to embedding similarity.

    Stage 2 (sklearn): If model_path exists, load and predict.
    Accept if predict_proba >= 0.7.

    Stage 3 (fallback): Return "unclassified".
    """
    category_names = list(prototypes.keys())
    scores: dict[str, float] = {}

    # ── Stage 1: TF-IDF prototype matching ───────────────────────
    if _sklearn_available:
        from sklearn.metrics.pairwise import cosine_similarity as cos_sim

        vectorizer, proto_matrix, proto_labels = _ensure_prototype_index(prototypes)
        text_vec = vectorizer.transform([text])
        sims = cos_sim(text_vec, proto_matrix)[0]
        best_idx = int(sims.argmax())
        best_score = float(sims[best_idx])
        best_cat = proto_labels[best_idx]

        for cat in category_names:
            cat_indices = [j for j, l in enumerate(proto_labels) if l == cat]
            scores[cat] = round(max(sims[j] for j in cat_indices), 3) if cat_indices else 0.0

        if best_score >= cascade_threshold and best_cat in category_names:
            return ClassifyResult(
                category=best_cat,
                stage="prototype",
                confidence=best_score,
                scores=scores,
            )

        # Low TF-IDF confidence — try embedding cascade
        if best_score >= min_similarity:
            embed_model, embed_matrix, embed_labels = _ensure_embed_index(prototypes)
            if embed_model is not None and embed_matrix is not None:
                import numpy as np
                embed_vec = np.array(list(embed_model.embed([text])))
                embed_sims = (embed_vec @ embed_matrix.T)[0]
                embed_best_idx = int(embed_sims.argmax())
                embed_cat = embed_labels[embed_best_idx]
                embed_score = float(embed_sims[embed_best_idx])

                if embed_cat in category_names:
                    return ClassifyResult(
                        category=embed_cat,
                        stage="prototype_embed",
                        confidence=embed_score,
                        scores=scores,
                    )

            # fastembed unavailable — accept TF-IDF result
            if best_cat in category_names:
                return ClassifyResult(
                    category=best_cat,
                    stage="prototype",
                    confidence=best_score,
                    scores=scores,
                )

    # ── Stage 2: sklearn classification ──────────────────────────
    if _sklearn_available and model_path and model_path.exists():
        global _cached_model, _cached_model_path
        if _cached_model_path != str(model_path) or _cached_model is None:
            try:
                _cached_model = joblib.load(model_path)
                _cached_model_path = str(model_path)
            except Exception:
                _cached_model = None
                _cached_model_path = None

        if _cached_model is not None:
            try:
                proba = _cached_model.predict_proba([text])[0]
                classes = _cached_model.classes_
                max_idx = proba.argmax()
                if proba[max_idx] >= 0.7:
                    return ClassifyResult(
                        category=classes[max_idx],
                        stage="sklearn",
                        confidence=float(proba[max_idx]),
                        scores=scores,
                    )
            except Exception:
                pass

    # ── Stage 3: Fallback ────────────────────────────────────────
    return ClassifyResult(
        category="unclassified",
        stage="fallback",
        confidence=0.0,
        scores=scores,
    )


def train_classifier(observations_dir: Path,
                     model_path: Path,
                     min_samples: int = 200) -> bool:
    """Train an sklearn classifier from accumulated labeled observations.

    Scans all JSONL files for reviewer_finding observations with a
    non-"unclassified" category. If count meets min_samples, trains
    a TfidfVectorizer + SGDClassifier pipeline and saves to model_path.

    Returns True if a model was trained and saved.
    """
    if not _sklearn_available:
        return False

    import json

    texts: list[str] = []
    labels: list[str] = []

    if not observations_dir.is_dir():
        return False

    for jsonl_file in observations_dir.glob("*.jsonl"):
        try:
            with open(jsonl_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        if obj.get("observation_type") != "reviewer_finding":
                            continue
                        detail = obj.get("detail", {})
                        category = detail.get("category", "")
                        if not category or category == "unclassified":
                            continue
                        finding = detail.get("finding", "")
                        if finding:
                            texts.append(finding)
                            labels.append(category)
                    except (json.JSONDecodeError, KeyError):
                        continue
        except OSError:
            continue

    if len(texts) < min_samples:
        return False

    # Train
    X_train, X_test, y_train, y_test = train_test_split(
        texts, labels, test_size=0.2, stratify=labels, random_state=42
    )

    pipeline = SkPipeline([
        ("tfidf", TfidfVectorizer(max_features=5000, ngram_range=(1, 2))),
        ("clf", SGDClassifier(loss="modified_huber", random_state=42)),
    ])
    pipeline.fit(X_train, y_train)

    accuracy = pipeline.score(X_test, y_test)
    print(f"Classifier trained: {len(texts)} samples, accuracy={accuracy:.2%}", file=os.sys.stderr)

    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, model_path)

    # Invalidate cache so next classify() picks up the new model
    global _cached_model, _cached_model_path
    _cached_model = None
    _cached_model_path = None

    return True


# ── Prototypes ───────────────────────────────────────────────────────

REVIEW_PROTOTYPES: dict[str, list[str]] = _load_prototypes(
    Path(__file__).parent / "data" / "review_categories.jsonl"
)
