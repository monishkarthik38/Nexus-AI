import os
import sys
import tempfile

import pytest


os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("QDRANT_COLLECTION", "nexus_documents_test_mock")
_TEST_QDRANT_DIRECTORY = tempfile.TemporaryDirectory(prefix="nexus-ai-test-qdrant-")
os.environ.setdefault("QDRANT_STORAGE_PATH", _TEST_QDRANT_DIRECTORY.name)


def pytest_unconfigure(config) -> None:
    indexer_module = sys.modules.get("app.retrieval.indexer")
    if indexer_module is not None:
        indexer_module.indexer.client.close()
    _TEST_QDRANT_DIRECTORY.cleanup()


@pytest.fixture(autouse=True)
def disable_inline_ingestion(monkeypatch) -> None:
    monkeypatch.setattr("app.config.settings.INGESTION_INLINE_DEVELOPMENT", False)
