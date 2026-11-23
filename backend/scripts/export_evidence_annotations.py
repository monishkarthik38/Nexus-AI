"""Export human labels as document-disjoint verifier train and test JSONL."""

import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from app.database.models import EvidenceAnnotation
from app.database.session import AsyncSessionLocal, set_session_tenant

BACKEND_DIR = Path(__file__).resolve().parents[1]


async def export(owner_id: str, test_document_ids_path: Path, train_output: Path, test_output: Path) -> None:
    test_document_ids = {
        line.strip()
        for line in test_document_ids_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    if not test_document_ids:
        raise ValueError("The test document ID file has no document IDs")

    async with AsyncSessionLocal() as db:
        set_session_tenant(db, owner_id)
        result = await db.execute(
            select(EvidenceAnnotation)
            .where(EvidenceAnnotation.owner_id == owner_id)
            .order_by(EvidenceAnnotation.created_at.asc())
        )
        annotations = result.scalars().all()

    if not annotations:
        raise ValueError(f"No human labels found for owner {owner_id!r}")
    found_test_document_ids = {row.document_id for row in annotations}.intersection(test_document_ids)
    if not found_test_document_ids:
        raise ValueError("None of the selected test document IDs have labeled examples")

    train_rows = []
    test_rows = []
    for row in annotations:
        item = {
            "id": row.id,
            "source_document_id": row.document_id,
            "passage": row.passage,
            "claim": row.claim,
            "label": row.label,
        }
        (test_rows if row.document_id in test_document_ids else train_rows).append(item)

    if not train_rows:
        raise ValueError("All labeled documents were assigned to test; leave some documents for training")

    for output_path, rows in ((train_output, train_rows), (test_output, test_rows)):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")

    print(json.dumps({
        "owner_id": owner_id,
        "train_examples": len(train_rows),
        "train_documents": len({row["source_document_id"] for row in train_rows}),
        "test_examples": len(test_rows),
        "test_documents": sorted(found_test_document_ids),
        "train_output": str(train_output.resolve()),
        "test_output": str(test_output.resolve()),
        "document_overlap": False,
    }, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner-id", required=True, help="Tenant whose labels will be exported")
    parser.add_argument("--test-document-ids", required=True, type=Path, help="Text file with one held-out document ID per line")
    parser.add_argument("--train-output", type=Path, default=BACKEND_DIR / "data" / "human_train.jsonl")
    parser.add_argument("--test-output", type=Path, default=BACKEND_DIR / "data" / "human_test.jsonl")
    args = parser.parse_args()
    asyncio.run(export(args.owner_id, args.test_document_ids, args.train_output, args.test_output))


if __name__ == "__main__":
    main()
