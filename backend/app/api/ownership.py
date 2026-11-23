from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Document


async def validate_owned_document_scope(
    db: AsyncSession,
    owner_id: str,
    document_ids: Optional[list[str]],
) -> Optional[list[str]]:
    if document_ids is None:
        return None

    scoped_ids = list(dict.fromkeys(document_ids))
    if not scoped_ids:
        return None

    result = await db.execute(
        select(Document.id).where(
            Document.id.in_(scoped_ids),
            Document.owner_id == owner_id,
        )
    )
    owned_ids = set(result.scalars().all())
    if owned_ids != set(scoped_ids):
        raise HTTPException(
            status_code=404,
            detail="One or more selected documents are unavailable.",
        )
    return scoped_ids
