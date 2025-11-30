from typing import Any, Dict, List

import numpy as np
from sentence_transformers import SentenceTransformer


class VectorStore:
    """
    더 이상 ChromaDB를 사용하지 않는 단순 in-memory 벡터 스토어입니다.
    현재 프로젝트 흐름에서는 사용하지 않지만, 기존 인터페이스 호환을 위해 남겨 둔 구현입니다.
    """

    def __init__(self) -> None:
        self.encoder = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        self._docs: List[Dict[str, Any]] = []
        self._embeddings: np.ndarray | None = None

    def index_docs(self, docs: List[Dict[str, Any]]) -> None:
        self._docs = docs
        texts = [d.get("text", "") for d in docs]
        emb = self.encoder.encode(texts, show_progress_bar=True)
        self._embeddings = np.asarray(emb, dtype="float32")

    def search(self, query: str, k: int = 20) -> List[Dict[str, Any]]:
        if self._embeddings is None or not self._docs:
            return []

        q_vec = self.encoder.encode([query])[0].astype("float32")
        # cosine similarity
        doc_norms = np.linalg.norm(self._embeddings, axis=1)
        q_norm = np.linalg.norm(q_vec)
        denom = (doc_norms * q_norm) + 1e-8
        sims = (self._embeddings @ q_vec) / denom

        idx = np.argsort(-sims)[:k]
        results: List[Dict[str, Any]] = []
        for i in idx:
            results.append(
                {
                    "score": float(sims[i]),
                    "doc": self._docs[i],
                }
            )
        return results

