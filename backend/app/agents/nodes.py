import re
from typing import Dict, Any, List
from app.agents.state import AgentState
from app.retrieval.search import searcher, SearchResult
from app.retrieval.reranker import reranker
from app.retrieval.grounded_answer import synthesizer, Citation, GroundedResponse
from app.nlp.language import detect_language, UNKNOWN_LANGUAGE

STOPWORDS = {"what", "is", "the", "how", "when", "who", "where", "why", "in", "and", "or", "a", "an", "for", "to", "of", "with", "does", "it", "use", "used"}

async def validate_question_node(state: AgentState) -> Dict[str, Any]:
    q = state.get("question", "").strip()
    response_language = state.get("response_language") or detect_language(q)
    logs = list(state.get("activity_logs", []))
    logs.append("Validating research query")

    if not q or len(q) < 3:
        return {
            "is_valid": False,
            "error": "Query is too short or empty.",
            "answer": "Please ask a specific question about your uploaded documents.",
            "response_language": response_language,
            "activity_logs": logs
        }

    lower_q = q.lower()
    suspicious_patterns = [
        "ignore all previous instructions",
        "system prompt override",
        "reveal your secret key",
        "drop table"
    ]
    if any(p in lower_q for p in suspicious_patterns):
        return {
            "is_valid": False,
            "error": "Query violated safety policies.",
            "answer": "This request violates safety policies and cannot be processed.",
            "response_language": response_language,
            "activity_logs": logs
        }

    return {"is_valid": True, "response_language": response_language, "activity_logs": logs}

async def classify_intent_node(state: AgentState) -> Dict[str, Any]:
    logs = list(state.get("activity_logs", []))
    logs.append("Classifying research intent")
    q = state.get("question", "").lower()

    if any(w in q for w in ["compare", "contrast", "difference", "versus", "vs"]):
        intent = "comparison"
    elif any(w in q for w in ["summarize", "overview", "summary", "main points", "tldr"]):
        intent = "summary"
    elif any(w in q for w in ["what", "who", "when", "where", "how much", "list"]):
        intent = "fact_lookup"
    else:
        intent = "general_inquiry"

    return {"intent": intent, "activity_logs": logs}

async def retrieve_evidence_node(state: AgentState) -> Dict[str, Any]:
    logs = list(state.get("activity_logs", []))
    query_to_search = state.get("rewritten_query") or state.get("question")
    retry_count = state.get("retry_count", 0)

    if retry_count > 0:
        logs.append(f"Searching documents with refined query (Attempt {retry_count + 1})")
    else:
        logs.append("Searching documents and retrieving relevant passages")

    raw_candidates = await searcher.search(
        query=query_to_search,
        owner_id=state["owner_id"],
        document_ids=state.get("document_ids"),
        top_k=8
    )

    ranked_candidates = reranker.rerank(query_to_search, raw_candidates, top_n=5)
    chunks_dict = [c.to_dict() for c in ranked_candidates]

    return {
        "retrieved_chunks": chunks_dict,
        "activity_logs": logs
    }

async def assess_evidence_node(state: AgentState) -> Dict[str, Any]:
    logs = list(state.get("activity_logs", []))
    logs.append("Assessing evidence sufficiency")
    chunks = state.get("retrieved_chunks", [])
    query = state.get("rewritten_query") or state.get("question", "")

    if not chunks:
        is_sufficient = False
    else:
        top_score = chunks[0]["score"] if chunks else 0
        q_words = set(re.findall(r"\w+", query.lower())) - STOPWORDS
        
        # Check factual term overlap in retrieved chunks
        overlap_found = False
        for c in chunks:
            c_words = set(re.findall(r"\w+", c.get("text", "").lower()))
            if q_words.intersection(c_words):
                overlap_found = True
                break

        # Evidence is sufficient if there is lexical overlap and sufficient score
        question_language = state.get("response_language") or detect_language(query)
        different_language = False
        if question_language != UNKNOWN_LANGUAGE:
            for chunk in chunks:
                chunk_language = detect_language(chunk.get("text", ""))
                if chunk_language != UNKNOWN_LANGUAGE and chunk_language != question_language:
                    different_language = True
                    break

        # Cross-language retrieval cannot depend on shared words; rely on dense
        # similarity when both sides have confidently different language tags.
        is_sufficient = (
            top_score > 0.45
            if different_language or not overlap_found
            else (top_score > 0.65) or (top_score > 0.10 and overlap_found)
        )

    return {
        "evidence_sufficient": is_sufficient,
        "activity_logs": logs
    }

async def rewrite_query_node(state: AgentState) -> Dict[str, Any]:
    logs = list(state.get("activity_logs", []))
    logs.append("Refining search terms for bounded retry")
    q = state.get("question", "")
    retry_count = state.get("retry_count", 0) + 1

    words = [w for w in re.findall(r"\w+", q) if len(w) > 3 and w.lower() not in STOPWORDS]
    rewritten = " ".join(words) if words else q

    return {
        "rewritten_query": rewritten,
        "retry_count": retry_count,
        "activity_logs": logs
    }

async def explain_knowledge_gap_node(state: AgentState) -> Dict[str, Any]:
    logs = list(state.get("activity_logs", []))
    logs.append("Documenting knowledge boundaries and evidence gaps")
    q = state.get("question", "")

    answer = (
        f"The uploaded documents do not contain sufficient evidence to answer: '{q}'. "
        "No matching passages or factual references were found across the current document scope."
    )

    return {
        "answer": answer,
        "citations": [],
        "claims": [],
        "confidence": "insufficient_evidence",
        "has_knowledge_gap": True,
        "activity_logs": logs
    }

async def generate_answer_node(state: AgentState) -> Dict[str, Any]:
    logs = list(state.get("activity_logs", []))
    logs.append("Synthesizing evidence-grounded answer")
    q = state.get("question", "")
    chunks_data = state.get("retrieved_chunks", [])

    search_results = [
        SearchResult(
            chunk_id=c["chunk_id"],
            document_id=c["document_id"],
            title=c["title"],
            page_number=c["page_number"],
            text=c["text"],
            score=c["score"],
            locator_type=c.get("locator_type", "page"),
            locator_value=c.get("locator_value")
        )
        for c in chunks_data
    ]

    resp: GroundedResponse = await synthesizer.generate_answer(
        q,
        search_results,
        response_language=state.get("response_language"),
    )
    citations_data = [c.model_dump() for c in resp.citations]

    return {
        "answer": resp.answer,
        "citations": citations_data,
        "claims": [claim.model_dump() for claim in resp.claims],
        "confidence": resp.confidence,
        "has_knowledge_gap": resp.has_knowledge_gap,
        "activity_logs": logs
    }

async def validate_citations_node(state: AgentState) -> Dict[str, Any]:
    logs = list(state.get("activity_logs", []))
    logs.append("Verifying citations against document chunks")
    raw_citations = state.get("citations", [])
    raw_claims = state.get("claims", [])
    chunks_data = state.get("retrieved_chunks", [])
    valid_ids = {c["chunk_id"] for c in chunks_data}

    verified = [c for c in raw_citations if c.get("source_id") in valid_ids]
    claims = [
        {
            **claim,
            "source_ids": [source_id for source_id in claim.get("source_ids", []) if source_id in valid_ids],
        }
        for claim in raw_claims
        if claim.get("text", "").strip()
    ]

    return {
        "citations": verified,
        "claims": claims,
        "activity_logs": logs
    }

async def format_response_node(state: AgentState) -> Dict[str, Any]:
    logs = list(state.get("activity_logs", []))
    logs.append("Research workflow completed")
    return {"activity_logs": logs}
