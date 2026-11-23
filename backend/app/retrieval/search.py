from typing import List, Optional, Dict, Any
from qdrant_client.http import models as qmodels
from app.config import settings
from app.retrieval.indexer import indexer
from app.retrieval.embeddings import embedding_service

class SearchResult:
    def __init__(self, chunk_id: str, document_id: str, title: str, page_number: int, text: str, score: float, locator_type: str = "page", locator_value: Optional[str] = None):
        self.chunk_id = chunk_id
        self.document_id = document_id
        self.title = title
        self.page_number = page_number
        self.text = text
        self.score = score
        self.locator_type = locator_type
        self.locator_value = locator_value or str(page_number)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "title": self.title,
            "page_number": self.page_number,
            "locator_type": self.locator_type,
            "locator_value": self.locator_value,
            "text": self.text,
            "score": round(self.score, 4)
        }

class QdrantSearcher:
    def __init__(self):
        self.client = indexer.client
        self.collection_name = settings.QDRANT_COLLECTION

    async def search(
        self,
        query: str,
        owner_id: str,
        document_ids: Optional[List[str]] = None,
        top_k: int = 5
    ) -> List[SearchResult]:
        if self.client is None:
            return []

        query_vector = await embedding_service.embed_query(query)

        filter_conditions = [
            qmodels.FieldCondition(
                key="owner_id",
                match=qmodels.MatchValue(value=owner_id)
            )
        ]

        if document_ids:
            if len(document_ids) == 1:
                filter_conditions.append(
                    qmodels.FieldCondition(
                        key="document_id",
                        match=qmodels.MatchValue(value=document_ids[0])
                    )
                )
            else:
                filter_conditions.append(
                    qmodels.FieldCondition(
                        key="document_id",
                        match=qmodels.MatchAny(any=document_ids)
                    )
                )

        search_filter = qmodels.Filter(must=filter_conditions)

        # Execute query_points in Qdrant 1.20+
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            query_filter=search_filter,
            limit=top_k,
            with_payload=True,
        )

        results: List[SearchResult] = []
        hits = getattr(response, "points", response)
        for hit in hits:
            p = hit.payload or {}
            stored_embedding = (
                p.get("embedding_provider"),
                p.get("embedding_model"),
                p.get("embedding_dimension"),
            )
            if any(value is not None for value in stored_embedding):
                current_embedding = (
                    embedding_service.provider,
                    embedding_service.model,
                    embedding_service.dimension,
                )
                if stored_embedding != current_embedding:
                    raise RuntimeError(
                        f"Qdrant collection '{self.collection_name}' contains vectors "
                        "created by a different embedding configuration. Use a separate "
                        "QDRANT_COLLECTION for each embedding model, then run "
                        "`python -m scripts.reindex_vectors` from the backend directory."
                    )
            results.append(SearchResult(
                chunk_id=p.get("chunk_id", ""),
                document_id=p.get("document_id", ""),
                title=p.get("title", ""),
                page_number=p.get("page_number", 1),
                text=p.get("text", ""),
                score=hit.score,
                locator_type=p.get("locator_type", "page"),
                locator_value=p.get("locator_value", str(p.get("page_number", 1)))
            ))

        return results

searcher = QdrantSearcher()
