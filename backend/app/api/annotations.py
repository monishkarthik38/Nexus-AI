from typing import Literal
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Document, DocumentChunk, EvidenceAnnotation
from app.database.session import get_db
from app.auth import CurrentUser, get_current_user

router = APIRouter(prefix="/api/evidence-annotations", tags=["Evidence annotations"])


class AnnotationRequest(BaseModel):
    source_id: str = Field(..., min_length=1, max_length=64)
    claim: str = Field(..., min_length=1, max_length=4000)
    label: Literal["supports", "contradicts", "insufficient"]


class DatasetExportRequest(BaseModel):
    test_document_ids: list[str] = Field(..., min_length=1)


@router.post("")
async def create_annotation(req: AnnotationRequest, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    query = (
        select(DocumentChunk, Document)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(DocumentChunk.id == req.source_id, Document.owner_id == user.id)
    )
    result = await db.execute(query)
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Source passage not found in this owner's documents")

    chunk, document = row
    existing_result = await db.execute(
        select(EvidenceAnnotation).where(
            EvidenceAnnotation.owner_id == user.id,
            EvidenceAnnotation.source_id == chunk.id,
            EvidenceAnnotation.claim == req.claim.strip(),
        )
    )
    annotation = existing_result.scalar_one_or_none()
    if annotation is None:
        annotation = EvidenceAnnotation(
            id=str(uuid.uuid4()),
            owner_id=user.id,
            document_id=document.id,
            source_id=chunk.id,
            claim=req.claim.strip(),
            passage=chunk.chunk_text,
            label=req.label,
        )
        db.add(annotation)
    else:
        annotation.label = req.label
        annotation.passage = chunk.chunk_text
    await db.commit()
    return {"id": annotation.id, "label": annotation.label, "document_id": document.id}


@router.get("/summary")
async def annotation_summary(user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    query = (
        select(EvidenceAnnotation, Document.filename)
        .join(Document, Document.id == EvidenceAnnotation.document_id)
        .where(EvidenceAnnotation.owner_id == user.id, Document.owner_id == user.id)
        .order_by(EvidenceAnnotation.created_at.asc())
    )
    result = await db.execute(query)
    rows = result.all()
    documents: dict[str, dict] = {}
    labels = {"supports": 0, "contradicts": 0, "insufficient": 0}
    for annotation, filename in rows:
        entry = documents.setdefault(annotation.document_id, {
            "document_id": annotation.document_id,
            "filename": filename,
            "count": 0,
            "labels": {"supports": 0, "contradicts": 0, "insufficient": 0},
        })
        entry["count"] += 1
        entry["labels"][annotation.label] += 1
        labels[annotation.label] += 1
    return {
        "total": len(rows),
        "labels": labels,
        "documents": list(documents.values()),
    }


@router.post("/export")
async def export_annotation_datasets(req: DatasetExportRequest, user: CurrentUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    test_document_ids = set(req.test_document_ids)
    query = (
        select(EvidenceAnnotation)
        .join(Document, Document.id == EvidenceAnnotation.document_id)
        .where(EvidenceAnnotation.owner_id == user.id, Document.owner_id == user.id)
        .order_by(EvidenceAnnotation.created_at.asc())
    )
    result = await db.execute(query)
    annotations = result.scalars().all()
    if not annotations:
        raise HTTPException(status_code=400, detail="Label claim/passage pairs from the Research Studio first")

    known_document_ids = {row.document_id for row in annotations}
    invalid_ids = test_document_ids - known_document_ids
    if invalid_ids:
        raise HTTPException(status_code=400, detail="Every selected test document must have at least one human label")

    train_rows = []
    test_rows = []
    for row in annotations:
        example = {
            "id": row.id,
            "source_document_id": row.document_id,
            "passage": row.passage,
            "claim": row.claim,
            "label": row.label,
        }
        (test_rows if row.document_id in test_document_ids else train_rows).append(example)

    if not train_rows:
        raise HTTPException(status_code=400, detail="Select held-out documents while leaving at least one labeled training document")
    if not test_rows:
        raise HTTPException(status_code=400, detail="No annotations found in the selected held-out documents")

    train_document_ids = {row["source_document_id"] for row in train_rows}
    test_output_document_ids = {row["source_document_id"] for row in test_rows}
    if train_document_ids.intersection(test_output_document_ids):
        raise HTTPException(status_code=500, detail="Internal error: document split is not disjoint")

    return {
        "train_jsonl": "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in train_rows),
        "test_jsonl": "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in test_rows),
        "train_examples": len(train_rows),
        "test_examples": len(test_rows),
        "train_documents": len(train_document_ids),
        "test_documents": len(test_output_document_ids),
    }
