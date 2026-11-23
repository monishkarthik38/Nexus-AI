import os
import uuid
import warnings
from typing import List
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from app.config import settings
from app.ingestion.chunker import TextChunk
from app.retrieval.embeddings import embedding_service

class QdrantIndexer:
    def __init__(self):
        self.collection_name = settings.QDRANT_COLLECTION
        self.using_in_memory_fallback = False
        self.client = self._create_client()
        self._ensure_collection()

    def _create_client(self):
        if settings.QDRANT_URL:
            return QdrantClient(
                url=settings.QDRANT_URL,
                api_key=settings.QDRANT_API_KEY,
            )

        os.makedirs(settings.QDRANT_STORAGE_PATH, exist_ok=True)
        try:
            return QdrantClient(path=settings.QDRANT_STORAGE_PATH)
        except RuntimeError as exc:
            message = str(exc)
            if "already accessed by another instance" in message or "Permission denied" in message:
                warnings.warn(
                    "Qdrant local storage is locked by another process; falling back to an in-memory instance for this process.",
                    RuntimeWarning,
                    stacklevel=2,
                )
                self.using_in_memory_fallback = True
                return QdrantClient(location=":memory:")
            raise

    def _ensure_collection(self) -> None:
        if self.client is None:
            raise RuntimeError("Qdrant client is unavailable; vector indexing cannot continue.")
        collections = self.client.get_collections().collections
        exists = any(c.name == self.collection_name for c in collections)
        if not exists:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=qmodels.VectorParams(
                    size=embedding_service.dimension,
                    distance=qmodels.Distance.COSINE,
                ),
            )
            return

        collection = self.client.get_collection(self.collection_name)
        vectors = collection.config.params.vectors
        collection_dimension = getattr(vectors, "size", None)
        if collection_dimension != embedding_service.dimension:
            raise RuntimeError(
                f"Qdrant collection '{self.collection_name}' uses "
                f"{collection_dimension!r}-dimension vectors, but the configured "
                f"{embedding_service.provider} embedding model requires "
                f"{embedding_service.dimension}. Choose a new QDRANT_COLLECTION "
                "and reindex stored document chunks before using this model."
            )

    async def index_chunks(self, chunks: List[TextChunk], owner_id: str) -> int:
        if not chunks:
            return 0
        if self.client is None:
            raise RuntimeError("Qdrant client is unavailable; vector indexing cannot continue.")

        texts = [c.text for c in chunks]
        vectors = await embedding_service.embed_texts(texts)
        if len(vectors) != len(chunks):
            raise RuntimeError(
                f"Embedding service returned {len(vectors)} vectors for {len(chunks)} chunks."
            )
        if any(len(vector) != embedding_service.dimension for vector in vectors):
            raise RuntimeError(
                f"Embedding vectors do not match the configured "
                f"{embedding_service.dimension}-dimension Qdrant collection."
            )

        points = []
        for chunk, vector in zip(chunks, vectors, strict=True):
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk.chunk_id))
            payload = {
                'chunk_id': chunk.chunk_id,
                'document_id': chunk.document_id,
                'page_number': chunk.page_number,
                'locator_type': getattr(chunk, 'locator_type', 'page'),
                'locator_value': getattr(chunk, 'locator_value', str(chunk.page_number)),
                'chunk_index': chunk.chunk_index,
                'title': chunk.title,
                'text': chunk.text,
                'content_hash': chunk.content_hash,
                'owner_id': owner_id,
                'embedding_provider': embedding_service.provider,
                'embedding_model': embedding_service.model,
                'embedding_dimension': embedding_service.dimension,
            }
            points.append(qmodels.PointStruct(
                id=point_id,
                vector=vector,
                payload=payload,
            ))

        self.client.upsert(
            collection_name=self.collection_name,
            points=points,
        )
        return len(points)

    def delete_document(self, document_id: str, owner_id: str) -> None:
        if self.client is None:
            return
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key='document_id',
                            match=qmodels.MatchValue(value=document_id),
                        ),
                        qmodels.FieldCondition(
                            key='owner_id',
                            match=qmodels.MatchValue(value=owner_id),
                        ),
                    ]
                )
            )
        )

indexer = QdrantIndexer()
