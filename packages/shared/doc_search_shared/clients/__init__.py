"""RAG wiring contract.

The two modules in this package are the wiring seam. When the real RAG system
is ready, replace ONLY the Fake implementations below. Grep ``TODO[wiring]``.
"""

from .rag_embedding_client import (
    FakeRagEmbeddingClient,
    IngestResult,
    RagEmbeddingClient,
)
from .rag_search_client import (
    FakeRagSearchClient,
    RagSearchClient,
    SearchHit,
)

__all__ = [
    "FakeRagEmbeddingClient",
    "FakeRagSearchClient",
    "IngestResult",
    "RagEmbeddingClient",
    "RagSearchClient",
    "SearchHit",
]
