"""Text embeddings.

The default embedder runs a small open model locally (ONNX via fastembed), so indexing and
search need no API key and no document text leaves the machine. Anything that satisfies the
`Embedder` protocol can replace it, as long as `embedding_dim` in the settings matches.
"""

from functools import lru_cache
from typing import Protocol

import numpy as np

from app.config import get_settings


class Embedder(Protocol):
    def embed_passages(self, texts: list[str]) -> list[np.ndarray]: ...

    def embed_query(self, text: str) -> np.ndarray: ...


class FastEmbedEmbedder:
    def __init__(self, model_name: str) -> None:
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name=model_name)

    def embed_passages(self, texts: list[str]) -> list[np.ndarray]:
        return list(self._model.passage_embed(texts))

    def embed_query(self, text: str) -> np.ndarray:
        return next(iter(self._model.query_embed(text)))


@lru_cache
def get_embedder() -> Embedder:
    return FastEmbedEmbedder(get_settings().embedding_model)
