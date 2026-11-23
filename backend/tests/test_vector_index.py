from types import SimpleNamespace

import pytest

from app.ingestion.chunker import TextChunk
from app.retrieval import indexer as indexer_module
from app.retrieval import search as search_module
from app.retrieval.indexer import QdrantIndexer
from app.retrieval.search import QdrantSearcher


def _chunk() -> TextChunk:
    return TextChunk(
        chunk_id="doc-1_p1_c0_hash",
        document_id="doc-1",
        page_number=1,
        chunk_index=0,
        title="notes.pdf",
        content_hash="hash",
        text="Source text for indexing.",
    )


def test_existing_collection_dimension_mismatch_fails_with_reindex_guidance(monkeypatch):
    monkeypatch.setattr(indexer_module.embedding_service, "dimension", 3)
    client = SimpleNamespace(
        get_collections=lambda: SimpleNamespace(
            collections=[SimpleNamespace(name="nexus_documents")]
        ),
        get_collection=lambda name: SimpleNamespace(
            config=SimpleNamespace(
                params=SimpleNamespace(vectors=SimpleNamespace(size=768))
            )
        ),
    )
    index = QdrantIndexer.__new__(QdrantIndexer)
    index.client = client
    index.collection_name = "nexus_documents"

    with pytest.raises(RuntimeError, match="requires 3"):
        index._ensure_collection()


def test_delete_filter_includes_document_and_owner():
    class FakeClient:
        delete_arguments = None

        def delete(self, **kwargs):
            self.delete_arguments = kwargs

    client = FakeClient()
    index = QdrantIndexer.__new__(QdrantIndexer)
    index.client = client
    index.collection_name = "nexus_documents"

    index.delete_document("doc-a", owner_id="tenant-a")

    conditions = client.delete_arguments["points_selector"].filter.must
    assert {(condition.key, condition.match.value) for condition in conditions} == {
        ("document_id", "doc-a"),
        ("owner_id", "tenant-a"),
    }


@pytest.mark.asyncio
async def test_indexing_rejects_missing_embeddings_before_upsert(monkeypatch):
    monkeypatch.setattr(indexer_module.embedding_service, "dimension", 3)
    monkeypatch.setattr(indexer_module.embedding_service, "provider", "test")
    monkeypatch.setattr(indexer_module.embedding_service, "model", "test-embed")

    async def incomplete_embeddings(texts):
        return []

    class FakeClient:
        upsert_called = False

        def upsert(self, **kwargs):
            self.upsert_called = True

    client = FakeClient()
    monkeypatch.setattr(
        indexer_module.embedding_service,
        "embed_texts",
        incomplete_embeddings,
    )
    index = QdrantIndexer.__new__(QdrantIndexer)
    index.client = client
    index.collection_name = "nexus_documents"

    with pytest.raises(RuntimeError, match="returned 0 vectors for 1 chunks"):
        await index.index_chunks([_chunk()], owner_id="owner-1")

    assert client.upsert_called is False


@pytest.mark.asyncio
async def test_indexing_writes_embedding_identity_to_point_payload(monkeypatch):
    monkeypatch.setattr(indexer_module.embedding_service, "dimension", 3)
    monkeypatch.setattr(indexer_module.embedding_service, "provider", "test")
    monkeypatch.setattr(indexer_module.embedding_service, "model", "test-embed")

    async def valid_embeddings(texts):
        return [[0.1, 0.2, 0.3] for _ in texts]

    class FakeClient:
        points = None

        def upsert(self, *, collection_name, points):
            self.points = points

    client = FakeClient()
    monkeypatch.setattr(
        indexer_module.embedding_service,
        "embed_texts",
        valid_embeddings,
    )
    index = QdrantIndexer.__new__(QdrantIndexer)
    index.client = client
    index.collection_name = "nexus_documents"

    count = await index.index_chunks([_chunk()], owner_id="owner-1")

    assert count == 1
    assert client.points[0].payload["owner_id"] == "owner-1"
    assert client.points[0].payload["embedding_provider"] == "test"
    assert client.points[0].payload["embedding_model"] == "test-embed"
    assert client.points[0].payload["embedding_dimension"] == 3


@pytest.mark.asyncio
async def test_search_rejects_vectors_from_another_embedding_configuration(monkeypatch):
    monkeypatch.setattr(search_module.embedding_service, "provider", "test")
    monkeypatch.setattr(search_module.embedding_service, "model", "current-model")
    monkeypatch.setattr(search_module.embedding_service, "dimension", 3)

    async def query_embedding(query):
        return [0.1, 0.2, 0.3]

    class FakeClient:
        def query_points(self, **kwargs):
            return SimpleNamespace(points=[
                SimpleNamespace(
                    payload={
                        "chunk_id": "chunk-1",
                        "document_id": "doc-1",
                        "embedding_provider": "test",
                        "embedding_model": "old-model",
                        "embedding_dimension": 3,
                    },
                    score=0.9,
                )
            ])

    monkeypatch.setattr(
        search_module.embedding_service,
        "embed_query",
        query_embedding,
    )
    searcher = QdrantSearcher.__new__(QdrantSearcher)
    searcher.client = FakeClient()
    searcher.collection_name = "nexus_documents"

    with pytest.raises(RuntimeError, match="different embedding configuration"):
        await searcher.search("question", owner_id="owner-1")


@pytest.mark.asyncio
async def test_search_filter_requires_owner_and_selected_documents(monkeypatch):
    async def query_embedding(_query):
        return [0.1, 0.2, 0.3]

    class FakeClient:
        query_arguments = None

        def query_points(self, **kwargs):
            self.query_arguments = kwargs
            return SimpleNamespace(points=[])

    monkeypatch.setattr(search_module.embedding_service, "embed_query", query_embedding)
    client = FakeClient()
    searcher = QdrantSearcher.__new__(QdrantSearcher)
    searcher.client = client
    searcher.collection_name = "nexus_documents"

    await searcher.search(
        "question",
        owner_id="tenant-b",
        document_ids=["tenant-b-doc-1", "tenant-b-doc-2"],
    )

    conditions = client.query_arguments["query_filter"].must
    assert [(condition.key, condition.match.value) for condition in conditions[:1]] == [
        ("owner_id", "tenant-b")
    ]
    assert conditions[1].key == "document_id"
    assert conditions[1].match.any == ["tenant-b-doc-1", "tenant-b-doc-2"]
