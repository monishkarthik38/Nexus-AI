# NEXUS evidence verifier (experimental)

The verifier is NEXUS's first trainable model component. It classifies a *claim + passage* pair as:

- `supports` — the passage provides evidence for the claim.
- `contradicts` — the passage conflicts with the claim.
- `insufficient` — the passage does not establish either conclusion.

It uses a TF-IDF word/character feature pipeline and logistic regression. It is a small, inspectable baseline—not a foundation model, proof engine, or production-quality fact checker. The included seed examples are synthetic and only demonstrate the workflow; metrics on them are not representative of real documents.

## Train and evaluate

From the `backend` directory, install requirements and run:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m scripts.train_evidence_verifier
```

The command makes a stratified holdout split, prints per-class precision/recall/F1 and a confusion matrix, and writes `models/evidence_verifier.joblib`. The generated artifact is intentionally git-ignored.

To use your own labeled JSONL file:

```powershell
.\venv\Scripts\python.exe -m scripts.train_evidence_verifier --dataset data/my_claim_pairs.jsonl --output models/my_verifier.joblib
```

Each line must be one JSON object with unique `id`, non-empty `passage`, non-empty `claim`, and `label` set to one of the three labels. Add labels based on human review of real passages from your intended domain. Keep a separate, representative test set untouched while developing; do not treat random splits of near-duplicate examples as independent validation.

Example record:

```json
{"id":"review-0001","passage":"The notice sets the deadline at 30 June.","claim":"The deadline is 30 June.","label":"supports"}
```

## Responsible use and next milestone

The model's output is a triage signal, not an authoritative verdict. In particular, `insufficient` means *this passage alone* is inadequate; another passage may provide the answer. The current chat evidence map still links model-generated claims to retrieved passages and does not automatically use this classifier to certify them.

## Collect labels from real documents

After asking a question in the app, use the three label buttons under a claim's cited passage. The API loads the passage from the indexed chunk belonging to the selected owner, rather than trusting passage text submitted by the browser. Labels are stored locally in the `evidence_annotations` table. Only label material you are allowed to use for model development; labels and passage snapshots may contain private document text.

To export labels, create a text file containing one or more document IDs to reserve for testing (one ID per line). Keep those entire documents out of training. Then, from `backend`, run:

```powershell
.\venv\Scripts\python.exe -m scripts.export_evidence_annotations --owner-id "actual-owner-id" --test-document-ids data\held_out_document_ids.txt
```

This writes `data/human_train.jsonl` and `data/human_test.jsonl`. Train on the first and evaluate on the second:

```powershell
.\venv\Scripts\python.exe -m scripts.train_evidence_verifier --dataset data\human_train.jsonl --test-dataset data\human_test.jsonl --output models\evidence_verifier.joblib
```

The trainer rejects overlapping document IDs and requires IDs on both datasets for this mode. Aim for multiple labeled documents and examples from all three classes; an empty or single-document test set is not a meaningful generalization check. Continue adding human-reviewed cases for disagreements and model errors, and preserve a separate test set that is not used to tune the model.

Before connecting it to live answers, collect a balanced and diverse human-labeled corpus, measure performance on a document-disjoint test set, review false-support and false-contradiction cases, and choose thresholds based on the cost of errors. Then wire predictions into the UI as suggestions with source excerpts and human review—not as claims of verified truth.
