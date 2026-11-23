import os
import uuid
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.session import get_db
from app.database.models import EvaluationRun
from app.evaluation.benchmark import EvaluationRunner
from app.auth import CurrentUser, get_current_user
from app.api.ownership import validate_owned_document_scope

router = APIRouter(prefix="/api/evaluation", tags=["Evaluation"])

DEFAULT_DATASET_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "evaluation", "questions.jsonl")
)

class EvaluationTriggerRequest(BaseModel):
    document_ids: Optional[List[str]] = Field(
        None, max_length=100, description="Optional document IDs to scope benchmark evaluation"
    )

@router.post("/run")
async def run_evaluation(
    req: EvaluationTriggerRequest,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    document_ids = await validate_owned_document_scope(
        db, user.id, req.document_ids
    )

    if not os.path.exists(DEFAULT_DATASET_PATH):
        raise HTTPException(status_code=404, detail=f"Benchmark questions file not found at {DEFAULT_DATASET_PATH}")

    runner = EvaluationRunner(dataset_path=DEFAULT_DATASET_PATH)
    try:
        report = await runner.run_evaluation(owner_id=user.id, document_ids=document_ids)
        
        # Save evaluation run to database
        run_record = EvaluationRun(
            id=str(uuid.uuid4()),
            owner_id=user.id,
            dataset_version=report["metrics"].get("dataset_version", "v1.0"),
            metrics=report["metrics"],
            status="completed"
        )
        db.add(run_record)
        await db.commit()

        return {
            "run_id": run_record.id,
            "status": "completed",
            "metrics": report["metrics"],
            "details": report["test_details"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {str(e)}")

@router.get("/runs")
async def list_evaluation_runs(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(EvaluationRun).where(EvaluationRun.owner_id == user.id).order_by(EvaluationRun.created_at.desc())
    res = await db.execute(stmt)
    runs = res.scalars().all()
    return [
        {
            "id": r.id,
            "dataset_version": r.dataset_version,
            "metrics": r.metrics,
            "status": r.status,
            "created_at": r.created_at.isoformat()
        }
        for r in runs
    ]
