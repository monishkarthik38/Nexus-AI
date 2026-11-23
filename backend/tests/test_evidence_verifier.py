import json
from pathlib import Path

import pytest

from app.evaluation.evidence_verifier import load_examples, predict_evidence, train_verifier


def test_seed_dataset_has_balanced_classes():
    dataset = Path(__file__).resolve().parents[1] / "data" / "evidence_verifier_seed.jsonl"
    examples = load_examples(dataset)
    labels = {label: sum(row["label"] == label for row in examples) for label in ("supports", "contradicts", "insufficient")}
    assert len(examples) == 36
    assert labels == {"supports": 12, "contradicts": 12, "insufficient": 12}


def test_trains_and_predicts_from_labeled_pairs(tmp_path):
    dataset = tmp_path / "pairs.jsonl"
    rows = [
        {"id": "s1", "passage": "The meeting is on Thursday.", "claim": "The meeting is on Thursday.", "label": "supports"},
        {"id": "s2", "passage": "The report names Mira as the project lead.", "claim": "Mira is the project lead.", "label": "supports"},
        {"id": "c1", "passage": "The meeting is on Thursday.", "claim": "The meeting is on Tuesday.", "label": "contradicts"},
        {"id": "c2", "passage": "The report names Mira as the project lead.", "claim": "Mira is not the project lead.", "label": "contradicts"},
        {"id": "i1", "passage": "The meeting is on Thursday.", "claim": "The office has 20 employees.", "label": "insufficient"},
        {"id": "i2", "passage": "The report names Mira as the project lead.", "claim": "The report was published in June.", "label": "insufficient"},
    ]
    dataset.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    model_path = tmp_path / "verifier.joblib"

    report = train_verifier(dataset, model_path, test_size=0.5)
    prediction = predict_evidence("The meeting is on Thursday.", "The meeting is on Thursday.", model_path)

    assert model_path.exists()
    assert report["dataset_size"] == 6
    assert set(report["class_counts"]) == {"supports", "contradicts", "insufficient"}
    assert prediction["label"] in {"supports", "contradicts", "insufficient"}
    assert 0.0 <= prediction["score"] <= 1.0
    assert "not evidence" in prediction["model_warning"]


def test_rejects_unknown_labels(tmp_path):
    dataset = tmp_path / "invalid.jsonl"
    dataset.write_text(json.dumps({"id": "bad", "passage": "Text", "claim": "Claim", "label": "maybe"}) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unknown label"):
        load_examples(dataset)


def test_external_evaluation_rejects_document_leakage(tmp_path):
    train_path = tmp_path / "train.jsonl"
    test_path = tmp_path / "test.jsonl"
    train_rows = [
        {"id": f"{label}-{index}", "source_document_id": f"train-doc-{index}", "passage": f"Passage {index} says yes.", "claim": f"Claim {index} yes.", "label": label}
        for label in ("supports", "contradicts", "insufficient")
        for index in range(2)
    ]
    test_rows = [
        {"id": f"test-{label}-{index}", "source_document_id": "held-out-doc", "passage": f"Held out passage {index}.", "claim": f"Held out claim {index}.", "label": label}
        for label in ("supports", "contradicts", "insufficient")
        for index in range(2)
    ]
    train_path.write_text("".join(json.dumps(row) + "\n" for row in train_rows), encoding="utf-8")
    test_path.write_text("".join(json.dumps(row) + "\n" for row in test_rows), encoding="utf-8")
    report = train_verifier(train_path, tmp_path / "external.joblib", test_dataset_path=test_path)
    assert report["evaluation"]["evaluation_split"] == "document_disjoint_external"
    assert report["evaluation"]["test_size"] == 6

    leaking_rows = [dict(row, source_document_id="train-doc-0") for row in test_rows]
    test_path.write_text("".join(json.dumps(row) + "\n" for row in leaking_rows), encoding="utf-8")
    with pytest.raises(ValueError, match="same source_document_id"):
        train_verifier(train_path, tmp_path / "leak.joblib", test_dataset_path=test_path)
