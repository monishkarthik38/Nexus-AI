from typing import TypedDict, List, Dict, Any, Optional, NotRequired

class AgentState(TypedDict):
    question: str
    response_language: NotRequired[str]
    owner_id: str
    document_ids: Optional[List[str]]
    is_valid: bool
    intent: str # fact_lookup, summary, comparison, unanswerable
    retrieved_chunks: List[Dict[str, Any]]
    retry_count: int
    max_retries: int
    rewritten_query: Optional[str]
    evidence_sufficient: bool
    answer: str
    citations: List[Dict[str, Any]]
    claims: List[Dict[str, Any]]
    confidence: str
    has_knowledge_gap: bool
    activity_logs: List[str]
    error: Optional[str]
