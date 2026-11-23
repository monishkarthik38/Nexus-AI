from langgraph.graph import StateGraph, END
from app.agents.state import AgentState
from app.agents.nodes import (
    validate_question_node,
    classify_intent_node,
    retrieve_evidence_node,
    assess_evidence_node,
    rewrite_query_node,
    explain_knowledge_gap_node,
    generate_answer_node,
    validate_citations_node,
    format_response_node
)

def route_after_validation(state: AgentState) -> str:
    if not state.get("is_valid", False):
        return "format_response"
    return "classify_intent"

def route_after_assessment(state: AgentState) -> str:
    if state.get("evidence_sufficient", False):
        return "generate_answer"
    # Insufficient evidence
    if state.get("retry_count", 0) < state.get("max_retries", 1):
        return "rewrite_query"
    return "explain_knowledge_gap"

def build_research_graph():
    workflow = StateGraph(AgentState)

    # Add all nodes
    workflow.add_node("validate_question", validate_question_node)
    workflow.add_node("classify_intent", classify_intent_node)
    workflow.add_node("retrieve_evidence", retrieve_evidence_node)
    workflow.add_node("assess_evidence", assess_evidence_node)
    workflow.add_node("rewrite_query", rewrite_query_node)
    workflow.add_node("explain_knowledge_gap", explain_knowledge_gap_node)
    workflow.add_node("generate_answer", generate_answer_node)
    workflow.add_node("validate_citations", validate_citations_node)
    workflow.add_node("format_response", format_response_node)

    # Set Entry Point
    workflow.set_entry_point("validate_question")

    # Conditional branch after question validation
    workflow.add_conditional_edges(
        "validate_question",
        route_after_validation,
        {
            "format_response": "format_response",
            "classify_intent": "classify_intent"
        }
    )

    workflow.add_edge("classify_intent", "retrieve_evidence")
    workflow.add_edge("retrieve_evidence", "assess_evidence")

    # Conditional branch after evidence assessment
    workflow.add_conditional_edges(
        "assess_evidence",
        route_after_assessment,
        {
            "generate_answer": "generate_answer",
            "rewrite_query": "rewrite_query",
            "explain_knowledge_gap": "explain_knowledge_gap"
        }
    )

    # Bounded retry loops back to retrieve_evidence
    workflow.add_edge("rewrite_query", "retrieve_evidence")

    # Grounded answer and knowledge gap flow into citation validation
    workflow.add_edge("generate_answer", "validate_citations")
    workflow.add_edge("explain_knowledge_gap", "validate_citations")
    workflow.add_edge("validate_citations", "format_response")
    workflow.add_edge("format_response", END)

    return workflow.compile()

research_graph = build_research_graph()
