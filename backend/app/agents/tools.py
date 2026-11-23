import asyncio
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.retrieval.search import searcher
from app.database.models import Document
from app.auth import CurrentUser

# 1. Tool Input Schemas
class SearchKBInput(BaseModel):
    query: str = Field(..., min_length=1, description="Keywords or natural language search query")
    document_ids: Optional[List[str]] = Field(None, description="Optional document IDs to filter")
    top_k: int = Field(5, ge=1, le=20, description="Number of results to retrieve")

class DocumentMetadataInput(BaseModel):
    document_id: str = Field(..., min_length=1, description="Document unique identifier")

# 2. Tool Implementations
async def tool_search_knowledge_base(
    args: Dict[str, Any],
    user: CurrentUser
) -> Dict[str, Any]:
    params = SearchKBInput(**args)
    results = await searcher.search(
        query=params.query,
        owner_id=user.id,
        document_ids=params.document_ids,
        top_k=params.top_k
    )
    return {
        "status": "success",
        "count": len(results),
        "results": [r.to_dict() for r in results]
    }

async def tool_get_document_metadata(
    args: Dict[str, Any],
    db: AsyncSession,
    user: CurrentUser
) -> Dict[str, Any]:
    params = DocumentMetadataInput(**args)
    stmt = select(Document).where(Document.id == params.document_id, Document.owner_id == user.id)
    res = await db.execute(stmt)
    doc = res.scalar_one_or_none()
    if not doc:
        return {"status": "error", "error": f"Document {params.document_id} not found."}
    return {
        "status": "success",
        "document": {
            "id": doc.id,
            "filename": doc.filename,
            "status": doc.status,
            "file_size": doc.file_size,
            "page_count": doc.page_count,
            "created_at": doc.created_at.isoformat()
        }
    }

# 3. Tool Registry and Dispatcher
ALLOWED_TOOLS = {
    "search_knowledge_base": tool_search_knowledge_base,
    "get_document_metadata": tool_get_document_metadata
}

async def execute_tool_safely(
    tool_name: str,
    args: Dict[str, Any],
    user: CurrentUser,
    db: Optional[AsyncSession] = None,
    timeout_seconds: float = 10.0
) -> Dict[str, Any]:
    if tool_name not in ALLOWED_TOOLS:
        return {"status": "error", "error": f"Tool '{tool_name}' is not permitted."}

    handler = ALLOWED_TOOLS[tool_name]
    try:
        if tool_name == "get_document_metadata":
            return await asyncio.wait_for(handler(args, db=db, user=user), timeout=timeout_seconds)
        else:
            return await asyncio.wait_for(handler(args, user=user), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        return {"status": "error", "error": f"Tool '{tool_name}' timed out after {timeout_seconds} seconds."}
    except Exception as e:
        return {"status": "error", "error": str(e)}
