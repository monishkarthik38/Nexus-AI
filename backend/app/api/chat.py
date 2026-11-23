import uuid
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.session import get_db
from app.database.models import Conversation, Message
from app.auth import CurrentUser, get_current_user
from app.agents.graph import research_graph
from app.agents.state import AgentState
from app.api.ownership import validate_owned_document_scope

router = APIRouter(prefix="/api/chat", tags=["Chat"])

class CitationModel(BaseModel):
    source_id: str
    document_id: str = ""
    document_name: str
    page_number: int
    excerpt: str
    locator_type: str = "page"
    locator_value: Optional[str] = None

class EvidenceClaimModel(BaseModel):
    text: str
    source_ids: List[str]

class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Question to answer grounded in uploaded documents")
    conversation_id: Optional[str] = Field(None, description="Optional conversation ID to continue a thread")
    document_ids: Optional[List[str]] = Field(
        None, max_length=100, description="Optional list of document IDs to scope retrieval"
    )

class ChatResponse(BaseModel):
    conversation_id: str
    query: str
    response_language: str
    answer: str
    citations: List[CitationModel]
    claims: List[EvidenceClaimModel]
    confidence: str
    has_knowledge_gap: bool
    retrieved_chunks_count: int
    activity_logs: List[str]

@router.post("", response_model=ChatResponse)
async def chat_query(
    req: ChatRequest,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    document_ids = await validate_owned_document_scope(
        db, user.id, req.document_ids
    )

    # 1. Resolve or create conversation
    conv_id = req.conversation_id
    if not conv_id:
        conv_id = str(uuid.uuid4())
        conv_record = Conversation(
            id=conv_id,
            owner_id=user.id,
            title=req.query[:60]
        )
        db.add(conv_record)
        await db.commit()
    else:
        stmt = select(Conversation).where(Conversation.id == conv_id, Conversation.owner_id == user.id)
        res = await db.execute(stmt)
        conv = res.scalar_one_or_none()
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")

    # 2. Record user query in DB
    user_msg = Message(
        conversation_id=conv_id,
        role="user",
        content=req.query
    )
    db.add(user_msg)
    await db.commit()

    # 3. Execute LangGraph research agent workflow
    initial_state: AgentState = {
        "question": req.query,
        "owner_id": user.id,
        "document_ids": document_ids,
        "is_valid": True,
        "intent": "fact_lookup",
        "retrieved_chunks": [],
        "retry_count": 0,
        "max_retries": 1,
        "rewritten_query": None,
        "evidence_sufficient": False,
        "answer": "",
        "citations": [],
        "claims": [],
        "confidence": "high",
        "has_knowledge_gap": False,
        "activity_logs": [],
        "error": None
    }

    final_state = await research_graph.ainvoke(initial_state)

    # 4. Record assistant response in DB
    citations_data = final_state.get("citations", [])
    assistant_msg = Message(
        conversation_id=conv_id,
        role="assistant",
        content=final_state.get("answer", ""),
        citations=citations_data
    )
    db.add(assistant_msg)
    await db.commit()

    citations_list = [
        CitationModel(
            source_id=c.get("source_id", ""),
            document_id=c.get("document_id", ""),
            document_name=c.get("document_name", ""),
            page_number=c.get("page_number", 1),
            excerpt=c.get("excerpt", ""),
            locator_type=c.get("locator_type", "page"),
            locator_value=c.get("locator_value")
        )
        for c in citations_data
    ]

    return ChatResponse(
        conversation_id=conv_id,
        query=req.query,
        response_language=final_state.get("response_language", "und"),
        answer=final_state.get("answer", ""),
        citations=citations_list,
        claims=[EvidenceClaimModel(**claim) for claim in final_state.get("claims", [])],
        confidence=final_state.get("confidence", "high"),
        has_knowledge_gap=final_state.get("has_knowledge_gap", False),
        retrieved_chunks_count=len(final_state.get("retrieved_chunks", [])),
        activity_logs=final_state.get("activity_logs", [])
    )

@router.get("/conversations")
async def list_conversations(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Conversation).where(Conversation.owner_id == user.id).order_by(Conversation.created_at.desc())
    res = await db.execute(stmt)
    convs = res.scalars().all()
    return [
        {
            "id": c.id,
            "title": c.title,
            "created_at": c.created_at.isoformat()
        }
        for c in convs
    ]

@router.get("/{conversation_id}")
async def get_conversation_history(
    conversation_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Conversation).where(Conversation.id == conversation_id, Conversation.owner_id == user.id)
    res = await db.execute(stmt)
    conv = res.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    msg_stmt = select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at.asc())
    msg_res = await db.execute(msg_stmt)
    msgs = msg_res.scalars().all()

    return {
        "conversation_id": conv.id,
        "title": conv.title,
        "created_at": conv.created_at.isoformat(),
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "citations": m.citations or [],
                "created_at": m.created_at.isoformat()
            }
            for m in msgs
        ]
    }

@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Conversation).where(Conversation.id == conversation_id, Conversation.owner_id == user.id)
    res = await db.execute(stmt)
    conv = res.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    await db.delete(conv)
    await db.commit()
    return {"status": "success", "message": f"Conversation {conversation_id} deleted."}
