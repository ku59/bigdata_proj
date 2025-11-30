from dataclasses import dataclass
from typing import Any, Dict, List

from sentence_transformers import SentenceTransformer

from src.retrieval.es_client import ESClient


@dataclass
class RetrievedDoc:
    text: str
    metadata: Dict[str, Any]
    hybrid_score: float
    sparse_score: float
    dense_score: float


class HybridRetriever:
    def __init__(self, alpha: float = 0.5) -> None:
        # ES 하나만 사용
        self.es = ESClient()
        self.encoder = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        self.alpha = alpha  # sparse/dense 가중치

    def retrieve(
        self,
        query: str,
        k: int = 10,
        corp_code: str | None = None,
        stock_code: str | None = None,
        year: str | None = None,
    ) -> List[RetrievedDoc]:
        # 1) Sparse (BM25) 검색
        sparse = self.es.search(
            query=query,
            size=k,
            corp_code=corp_code,
            stock_code=stock_code,
            year=year,
        )

        # 2) Dense 검색: 쿼리 임베딩 → ES knn_search
        q_vec = self.encoder.encode(query, convert_to_numpy=True).tolist()
        dense = self.es.knn_search(
            query_vector=q_vec,
            size=k,
            corp_code=corp_code,
            stock_code=stock_code,
            year=year,
        )

        # text 기준으로 dense 결과 매핑
        dense_map = {
            d["doc"].get("text"): d
            for d in dense
            if "doc" in d and isinstance(d["doc"], dict) and "text" in d["doc"]
        }

        results: List[RetrievedDoc] = []

        if sparse:
            # sparse 우선, 동일 text가 dense에 있으면 hybrid score로 병합
            for s in sparse:
                text = s["doc"].get("text", "")
                sparse_score = float(s.get("score", 0.0))
                dense_score = float(dense_map.get(text, {}).get("score", 0.0))
                hybrid_score = self.alpha * sparse_score + (1.0 - self.alpha) * dense_score

                results.append(
                    RetrievedDoc(
                        text=text,
                        metadata={k: v for k, v in s["doc"].items() if k != "text"},
                        hybrid_score=hybrid_score,
                        sparse_score=sparse_score,
                        dense_score=dense_score,
                    )
                )

            # sparse에 없는 dense-only 문서 추가
            sparse_texts = {s["doc"].get("text", "") for s in sparse}
            for d in dense:
                text = d["doc"].get("text", "")
                if text in sparse_texts:
                    continue
                dense_score = float(d.get("score", 0.0))
                hybrid_score = (1.0 - self.alpha) * dense_score
                results.append(
                    RetrievedDoc(
                        text=text,
                        metadata={k: v for k, v in d["doc"].items() if k != "text"},
                        hybrid_score=hybrid_score,
                        sparse_score=0.0,
                        dense_score=dense_score,
                    )
                )
        else:
            # sparse가 비었을 때는 dense-only 결과 반환
            for d in dense:
                text = d["doc"].get("text", "")
                dense_score = float(d.get("score", 0.0))
                hybrid_score = (1.0 - self.alpha) * dense_score
                results.append(
                    RetrievedDoc(
                        text=text,
                        metadata={k: v for k, v in d["doc"].items() if k != "text"},
                        hybrid_score=hybrid_score,
                        sparse_score=0.0,
                        dense_score=dense_score,
                    )
                )

        # hybrid_score 기준 정렬 후 상위 k개
        results.sort(key=lambda x: x.hybrid_score, reverse=True)
        return results[:k]

