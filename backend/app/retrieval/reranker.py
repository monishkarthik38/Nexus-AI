import re
from typing import List
from app.retrieval.search import SearchResult

TOKEN_PATTERN = re.compile(r"\w+")
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "does", "for", "from",
    "how", "in", "is", "it", "of", "on", "or", "the", "to", "was", "what",
    "when", "where", "which", "who", "why", "with",
}


class DocumentReranker:
    def __init__(self):
        pass

    def rerank(self, query: str, candidates: List[SearchResult], top_n: int = 5) -> List[SearchResult]:
        if not candidates:
            return []

        q_terms = {
            token
            for token in TOKEN_PATTERN.findall(query.casefold())
            if len(token) > 2 and token not in STOPWORDS
        }
        scored_candidates = []

        for c in candidates:
            text_terms = set(TOKEN_PATTERN.findall(c.text.casefold()))
            title_terms = set(TOKEN_PATTERN.findall(c.title.casefold()))
            denominator = max(len(q_terms), 1)
            lexical_coverage = len(q_terms & text_terms) / denominator
            title_coverage = len(q_terms & title_terms) / denominator

            combined_score = (
                0.7 * c.score
                + 0.25 * lexical_coverage
                + 0.05 * title_coverage
            )
            scored_candidates.append(SearchResult(
                chunk_id=c.chunk_id,
                document_id=c.document_id,
                title=c.title,
                page_number=c.page_number,
                text=c.text,
                score=combined_score,
                locator_type=c.locator_type,
                locator_value=c.locator_value,
            ))

        # Sort descending by combined score
        scored_candidates.sort(key=lambda x: x.score, reverse=True)
        return scored_candidates[:top_n]

reranker = DocumentReranker()
