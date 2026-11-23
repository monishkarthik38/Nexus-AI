"""Train and run the experimental NEXUS claim-to-passage evidence verifier."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

LABELS = ("supports", "contradicts", "insufficient")


def load_examples(dataset_path: str | Path) -> list[dict[str, str]]:
    examples: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    with Path(dataset_path).open("r", encoding="utf-8") as dataset_file:
        for line_number, raw_line in enumerate(dataset_file, start=1):
            if not raw_line.strip():
                continue
            try:
                row = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {line_number}: {exc.msg}") from exc

            required = ("id", "passage", "claim", "label")
            missing = [field for field in required if not isinstance(row.get(field), str) or not row[field].strip()]
            if missing:
                raise ValueError(f"Line {line_number} is missing non-empty fields: {', '.join(missing)}")
            if row["label"] not in LABELS:
                raise ValueError(f"Line {line_number} has unknown label {row['label']!r}; use {', '.join(LABELS)}")
            if row["id"] in seen_ids:
                raise ValueError(f"Duplicate example id {row['id']!r} on line {line_number}")

            seen_ids.add(row["id"])
            example = {field: row[field].strip() for field in required}
            if row.get("source_document_id") is not None:
                if not isinstance(row["source_document_id"], str) or not row["source_document_id"].strip():
                    raise ValueError(f"Line {line_number} has an empty source_document_id")
                example["source_document_id"] = row["source_document_id"].strip()
            examples.append(example)

    if not examples:
        raise ValueError("Dataset is empty")
    return examples


def pair_text(passage: str, claim: str) -> str:
    """Keep claim and evidence roles explicit for the pair classifier."""
    return f"passage: {passage}\nclaim: {claim}"


def build_pipeline():
    """Return a compact, inspectable TF-IDF + logistic regression classifier."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.pipeline import FeatureUnion
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline

    features = FeatureUnion([
        ("word", TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True)),
        ("character", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)),
    ])
    return Pipeline([
        ("features", features),
        ("classifier", LogisticRegression(max_iter=1000, class_weight="balanced", random_state=42)),
    ])


def train_verifier(
    dataset_path: str | Path,
    output_path: str | Path,
    test_size: float = 0.25,
    test_dataset_path: str | Path | None = None,
) -> dict[str, Any]:
    """Train an experimental verifier and persist its pipeline and metadata."""
    from collections import Counter

    import joblib
    from sklearn.metrics import classification_report, confusion_matrix
    from sklearn.model_selection import train_test_split

    examples = load_examples(dataset_path)
    labels = [row["label"] for row in examples]
    counts = Counter(labels)
    missing_labels = [label for label in LABELS if counts[label] < 2]
    if missing_labels:
        raise ValueError(f"Need at least two labeled examples for each class; missing: {', '.join(missing_labels)}")

    texts = [pair_text(row["passage"], row["claim"]) for row in examples]
    if test_dataset_path:
        test_examples = load_examples(test_dataset_path)
        if not all(row.get("source_document_id") for row in examples):
            raise ValueError("Every training example must include source_document_id when using an external test dataset")
        if not all(row.get("source_document_id") for row in test_examples):
            raise ValueError("Every external test example must include source_document_id for leakage checks")
        train_document_ids = {row.get("source_document_id") for row in examples if row.get("source_document_id")}
        test_document_ids = {row.get("source_document_id") for row in test_examples if row.get("source_document_id")}
        if train_document_ids.intersection(test_document_ids):
            raise ValueError("Training and test datasets contain the same source_document_id; split by document")
        x_train = texts
        y_train = labels
        x_test = [pair_text(row["passage"], row["claim"]) for row in test_examples]
        y_test = [row["label"] for row in test_examples]
    else:
        x_train, x_test, y_train, y_test = train_test_split(
            texts,
            labels,
            test_size=test_size,
            random_state=42,
            stratify=labels,
        )
    pipeline = build_pipeline()
    pipeline.fit(x_train, y_train)
    predictions = pipeline.predict(x_test)
    report = classification_report(y_test, predictions, labels=list(LABELS), output_dict=True, zero_division=0)
    matrix = confusion_matrix(y_test, predictions, labels=list(LABELS)).tolist()

    artifact = {
        "pipeline": pipeline,
        "labels": list(LABELS),
        "dataset_path": str(Path(dataset_path).resolve()),
        "test_dataset_path": str(Path(test_dataset_path).resolve()) if test_dataset_path else None,
        "dataset_size": len(examples),
        "class_counts": dict(counts),
        "evaluation": {
            "test_size": len(y_test),
            "macro_f1": report["macro avg"]["f1-score"],
            "evaluation_split": "document_disjoint_external" if test_dataset_path else "random_stratified_example_split",
            "classification_report": report,
            "confusion_matrix_labels": list(LABELS),
            "confusion_matrix": matrix,
        },
        "warning": "Experimental baseline only. A small or synthetic dataset is not evidence of production accuracy.",
    }
    artifact_path = Path(output_path)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, artifact_path)
    return {key: value for key, value in artifact.items() if key != "pipeline"} | {"model_path": str(artifact_path.resolve())}


def predict_evidence(passage: str, claim: str, model_path: str | Path) -> dict[str, Any]:
    """Classify one passage/claim pair; this prediction is not proof of truth."""
    import joblib

    artifact = joblib.load(model_path)
    pipeline = artifact["pipeline"]
    probabilities = pipeline.predict_proba([pair_text(passage, claim)])[0]
    labels = pipeline.classes_
    best_index = int(probabilities.argmax())
    return {
        "label": str(labels[best_index]),
        "score": float(probabilities[best_index]),
        "model_warning": artifact["warning"],
    }
