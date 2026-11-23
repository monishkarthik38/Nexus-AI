import math
import hashlib
import numpy as np
from typing import List
from app.config import settings

class EmbeddingService:
    def __init__(self):
        self.provider = settings.LLM_PROVIDER.lower()
        self.api_key = settings.openai_api_key
        self.model = (
            settings.OLLAMA_EMBEDDING_MODEL
            if self.provider == 'ollama'
            else settings.EMBEDDING_MODEL
        )

        if self.provider == 'openai':
            self.dimension = 1536
        elif self.provider == 'ollama':
            self.dimension = settings.OLLAMA_EMBEDDING_DIMENSION
        else: # legacy Gemini or deterministic fallback
            self.dimension = 768

    def _generate_deterministic_fallback(self, text: str) -> List[float]:
        # Hash-based pseudo-semantic normalized embedding for test/mock/offline mode
        words = text.lower().split()
        vec = np.zeros(self.dimension, dtype=np.float32)
        if not words:
            vec[0] = 1.0
            return vec.tolist()

        for w in words:
            h = int(hashlib.md5(w.encode('utf-8')).hexdigest(), 16)
            idx = h % self.dimension
            sign = 1.0 if (h % 2 == 0) else -1.0
            vec[idx] += sign

        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        else:
            vec[0] = 1.0
        return vec.tolist()

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        if self.provider in {'openai', 'ollama'}:
            is_ollama = self.provider == 'ollama'
            if not is_ollama and not self.api_key:
                raise RuntimeError('OpenAI embeddings require a valid LLM_API_KEY or OPENAI_API_KEY.')
            try:
                from openai import AsyncOpenAI
                client = AsyncOpenAI(
                    api_key='ollama' if is_ollama else self.api_key,
                    base_url=f'{settings.OLLAMA_BASE_URL.rstrip("/")}/v1' if is_ollama else None,
                )
                response = await client.embeddings.create(input=texts, model=self.model)
                vectors = [item.embedding for item in response.data]
                if any(len(vector) != self.dimension for vector in vectors):
                    raise RuntimeError(
                        f'{self.provider} embeddings do not match the configured '
                        f'{self.dimension}-dimension Qdrant collection.'
                    )
                return vectors
            except RuntimeError:
                raise
            except Exception as error:
                provider_name = 'Ollama' if is_ollama else 'OpenAI'
                raise RuntimeError(
                    f'{provider_name} embeddings failed. Check that the embedding model '
                    'is configured and available.'
                ) from error

        # Preserve the legacy Gemini provider for existing installations.
        if self.provider == 'gemini' and self.api_key and self.api_key != 'your_gemini_or_openai_api_key_here':
            try:
                from google import genai
                client = genai.Client(api_key=self.api_key)
                response = client.models.embed_content(
                    model=self.model,
                    contents=texts
                )
                return [e.values for e in response.embeddings]
            except Exception as e:
                print(f'Gemini embedding error: {e}. Falling back to deterministic embedding.')

        if self.provider not in {'mock', 'gemini'}:
            raise RuntimeError(f'Unsupported LLM_PROVIDER: {self.provider}.')

        return [self._generate_deterministic_fallback(t) for t in texts]

    async def embed_query(self, query: str) -> List[float]:
        results = await self.embed_texts([query])
        return results[0]

embedding_service = EmbeddingService()
