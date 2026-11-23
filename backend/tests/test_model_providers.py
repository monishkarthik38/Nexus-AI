import json
from types import SimpleNamespace

import openai
import pytest

from app.config import settings
from app.retrieval.embeddings import EmbeddingService
from app.retrieval.grounded_answer import GroundedSynthesizer
from app.retrieval.search import SearchResult
from app.ingestion.media_parser import MediaParser


def _set_provider_settings(monkeypatch, provider: str) -> None:
    monkeypatch.setattr(settings, "LLM_PROVIDER", provider)
    monkeypatch.setattr(settings, "LLM_API_KEY", None)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)
    monkeypatch.setattr(settings, "LLM_MODEL", "qwen3:8b" if provider == "ollama" else "gpt-4o-mini")


@pytest.mark.asyncio
async def test_ollama_answer_uses_openai_compatible_local_endpoint(monkeypatch):
    _set_provider_settings(monkeypatch, "ollama")
    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", "http://127.0.0.1:11434/")
    prompt_response = {
        "answer": "The source describes the experiment.",
        "claims": [],
        "citations": [],
        "confidence": "insufficient_evidence",
        "has_knowledge_gap": True,
    }
    request_options = {}

    class FakeClient:
        def __init__(self, *, api_key, base_url, timeout, max_retries):
            request_options["api_key"] = api_key
            request_options["base_url"] = base_url
            request_options["timeout"] = timeout
            request_options["max_retries"] = max_retries
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(
                    create=self.create_completion,
                )
            )

        async def create_completion(self, **kwargs):
            request_options["completion"] = kwargs
            return SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(prompt_response))
                )]
            )

    monkeypatch.setattr(openai, "AsyncOpenAI", FakeClient)
    result = await GroundedSynthesizer().generate_answer(
        "Explain the experiment",
        [SearchResult("chunk-1", "doc-1", "lab.pdf", 1, "Experiment notes.", 1)],
        answer_style="study_guide",
    )

    assert result.answer == prompt_response["answer"]
    assert request_options["api_key"] == "ollama"
    assert request_options["base_url"] == "http://127.0.0.1:11434/v1"
    assert request_options["completion"]["model"] == "qwen3:8b"
    assert request_options["completion"]["max_tokens"] == 1100
    assert request_options["completion"]["extra_body"] == {"think": False}
    assert request_options["completion"]["temperature"] == 0.2
    assert request_options["timeout"] == 300.0
    assert request_options["max_retries"] == 0


@pytest.mark.asyncio
async def test_openai_answer_requires_a_real_api_key(monkeypatch):
    _set_provider_settings(monkeypatch, "openai")

    with pytest.raises(RuntimeError, match="OpenAI generation requires a valid"):
        await GroundedSynthesizer().generate_answer(
            "Explain the experiment",
            [SearchResult("chunk-1", "doc-1", "lab.pdf", 1, "Experiment notes.", 1)],
        )


@pytest.mark.asyncio
async def test_openai_answer_accepts_openai_api_key_environment_setting(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(settings, "LLM_API_KEY", "your_openai_api_key_here")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "unit-test-key")
    monkeypatch.setattr(settings, "LLM_MODEL", "gpt-4o-mini")
    request_options = {}
    response_json = {
        "answer": "The source describes the experiment.",
        "claims": [],
        "citations": [],
        "confidence": "insufficient_evidence",
        "has_knowledge_gap": True,
    }

    class FakeClient:
        def __init__(self, *, api_key, base_url, timeout, max_retries):
            request_options["api_key"] = api_key
            request_options["base_url"] = base_url
            request_options["timeout"] = timeout
            request_options["max_retries"] = max_retries
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self.create_completion)
            )

        async def create_completion(self, **kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(response_json))
                )]
            )

    monkeypatch.setattr(openai, "AsyncOpenAI", FakeClient)
    result = await GroundedSynthesizer().generate_answer(
        "Explain the experiment",
        [SearchResult("chunk-1", "doc-1", "lab.pdf", 1, "Experiment notes.", 1)],
    )

    assert result.answer == response_json["answer"]
    assert request_options == {
        "api_key": "unit-test-key",
        "base_url": None,
        "timeout": 60.0,
        "max_retries": 0,
    }


@pytest.mark.asyncio
async def test_ollama_embeddings_use_configured_local_model(monkeypatch):
    _set_provider_settings(monkeypatch, "ollama")
    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setattr(settings, "OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
    monkeypatch.setattr(settings, "OLLAMA_EMBEDDING_DIMENSION", 3)
    request_options = {}

    class FakeClient:
        def __init__(self, *, api_key, base_url):
            request_options["api_key"] = api_key
            request_options["base_url"] = base_url
            self.embeddings = SimpleNamespace(create=self.create_embeddings)

        async def create_embeddings(self, *, input, model):
            request_options["input"] = input
            request_options["model"] = model
            return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3])])

    monkeypatch.setattr(openai, "AsyncOpenAI", FakeClient)
    vectors = await EmbeddingService().embed_texts(["A local embedding test"])

    assert vectors == [[0.1, 0.2, 0.3]]
    assert request_options == {
        "api_key": "ollama",
        "base_url": "http://127.0.0.1:11434/v1",
        "input": ["A local embedding test"],
        "model": "nomic-embed-text",
    }


@pytest.mark.asyncio
async def test_ollama_embedding_dimension_mismatch_is_explicit(monkeypatch):
    _set_provider_settings(monkeypatch, "ollama")
    monkeypatch.setattr(settings, "OLLAMA_EMBEDDING_DIMENSION", 3)

    class FakeClient:
        def __init__(self, **kwargs):
            self.embeddings = SimpleNamespace(
                create=self.create_embeddings,
            )

        async def create_embeddings(self, **kwargs):
            return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2])])

    monkeypatch.setattr(openai, "AsyncOpenAI", FakeClient)

    with pytest.raises(RuntimeError, match="do not match the configured 3-dimension"):
        await EmbeddingService().embed_texts(["A local embedding test"])


def test_ollama_vision_uses_local_openai_compatible_chat(monkeypatch):
    _set_provider_settings(monkeypatch, "ollama")
    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    request_options = {}

    class FakeClient:
        def __init__(self, *, api_key, base_url):
            request_options["api_key"] = api_key
            request_options["base_url"] = base_url
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self.create_completion)
            )

        def create_completion(self, **kwargs):
            request_options["completion"] = kwargs
            return SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(content="A clear image description.")
                )]
            )

    monkeypatch.setattr(openai, "OpenAI", FakeClient)
    descriptions = MediaParser._describe_images(["data:image/jpeg;base64,dGVzdA=="])

    assert descriptions == ["A clear image description."]
    assert request_options["api_key"] == "ollama"
    assert request_options["base_url"] == "http://127.0.0.1:11434/v1"
    assert request_options["completion"]["model"] == "qwen3:8b"
