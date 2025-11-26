from dataclasses import dataclass
from typing import Any, Dict, List

from src.retrieval.es_client import ESClient
from src.retrieval.vectorstore import VectorStore


@dataclass
class RetrievedDoc:
    text: str
    metadata: Dict[str, Any]
    hybrid_score: float
    sparse_score: float
    dense_score: float


class HybridRetriever:
    def __init__(self, alpha: float = 0.5) -> None:
        self.es = ESClient()
        self.vs = VectorStore()
        self.alpha = alpha

    def retrieve(self, query: str, k: int = 10) -> List[RetrievedDoc]:
        sparse = self.es.search(query, size=k)
        dense = self.vs.search(query, k=k)

        # id 없이 들어오므로 text를 기준으로 단순 merge (실제 서비스에선 고유 id 사용 권장)
        dense_map = {d["doc"]["text"]: d for d in dense}

        results: List[RetrievedDoc] = []
        for s in sparse:
            text = s["doc"]["text"]
            sparse_score = s["score"]
            dense_score = dense_map.get(text, {}).get("score", 0.0)
            hybrid_score = self.alpha * sparse_score + (1 - self.alpha) * dense_score
            results.append(
                RetrievedDoc(
                    text=text,
                    metadata={k: v for k, v in s["doc"].items() if k != "text"},
                    hybrid_score=hybrid_score,
                    sparse_score=sparse_score,
                    dense_score=dense_score,
                )
            )

        results.sort(key=lambda x: x.hybrid_score, reverse=True)
        return results[:k]

