import pytest

from app.agents.nodes import assess_evidence_node
from app.nlp.language import UNKNOWN_LANGUAGE, detect_language
from app.retrieval.grounded_answer import GroundedSynthesizer
from app.retrieval.search import SearchResult


@pytest.mark.parametrize(
    ("text", "expected_language"),
    [
        ("¿Cuál es el propósito principal de esta investigación? Resume los resultados y recomendaciones en español.", "es"),
        ("हिंदी में इस दस्तावेज़ का सारांश बताइए।", "hi"),
        ("Veuillez résumer les principaux risques de ce rapport.", "fr"),
        ("この文書の主な結論を説明してください。", "ja"),
    ],
)
def test_detect_language_for_multilingual_questions(text, expected_language):
    assert detect_language(text) == expected_language


def test_short_or_ambiguous_text_has_unknown_language():
    assert detect_language("OK") == UNKNOWN_LANGUAGE


def test_answer_prompt_preserves_question_language_and_source_quotes():
    synthesizer = GroundedSynthesizer()
    prompt = synthesizer._build_context_prompt(
        "¿Qué sistema utiliza la empresa?",
        [],
        response_language="es",
    )

    assert "same language as the user's question" in prompt
    assert "language tag: es" in prompt
    assert "Do not translate source excerpts or document names" in prompt
    study_prompt = synthesizer._build_context_prompt(
        "Prepare clear notes for this experiment",
        [],
        response_language="en",
        answer_style="study_guide",
    )
    assert "answer every distinct question" in study_prompt.lower()
    assert "not stated in the PDF" in study_prompt
    assert "line by line" in study_prompt
    assert "patient expert tutor" in study_prompt
    assert "Do not move explanatory content into a claims list" in study_prompt


@pytest.mark.asyncio
async def test_cross_language_evidence_assessment_uses_dense_similarity():
    state = {
        "question": "¿Qué sistema utiliza la empresa para gestionar sus documentos?",
        "response_language": "es",
        "retrieved_chunks": [{
            "text": "The company uses the Qdrant vector database to manage document storage.",
            "score": 0.5,
        }],
        "activity_logs": [],
    }

    result = await assess_evidence_node(state)
    assert result["evidence_sufficient"] is True


@pytest.mark.asyncio
async def test_question_validation_detects_response_language():
    from app.agents.nodes import validate_question_node

    result = await validate_question_node({
        "question": "¿Cuál es el propósito principal de esta investigación? Resume los resultados y recomendaciones en español.",
        "activity_logs": [],
    })
    assert result["response_language"] == "es"
