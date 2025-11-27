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

    def retrieve(
        self,
        query: str,
        k: int = 10,
        corp_code: str | None = None,
        stock_code: str | None = None,
        year: str | None = None,
    ) -> List[RetrievedDoc]:
        # 회사 코드/연도가 주어지면 ES에 필터를 적용하여 해당 회사/연도 중심의 근거를 우선 확보
        sparse = self.es.search(query, size=k, corp_code=corp_code, stock_code=stock_code, year=year)
        dense = self.vs.search(query, k=k)

        # id 없이 들어오므로 text를 기준으로 단순 merge (실제 서비스에선 고유 id 사용 권장)
        dense_map = {d["doc"]["text"]: d for d in dense}

        results: List[RetrievedDoc] = []

        if sparse:
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
        else:
            # ES 검색 실패/타임아웃 등으로 sparse가 비어도, 벡터 검색 결과만으로 반환
            # 회사 코드가 있는 경우, 벡터 결과 중 해당 회사 코드 메타데이터가 있는 문서를 우선 사용
            filtered_dense = []
            if corp_code or stock_code or year:
                for d in dense:
                    meta = {k: v for k, v in d["doc"].items() if k != "text"}
                    ok_company = True
                    if corp_code or stock_code:
                        ok_company = (
                            (corp_code and str(meta.get("company_code", "")) == str(corp_code))
                            or (stock_code and str(meta.get("stock_code", "")) == str(stock_code))
                        )
                    ok_year = True
                    if year:
                        ok_year = str(meta.get("year", "")) == str(year)
                    if ok_company and ok_year:
                        filtered_dense.append(d)
            use_dense = filtered_dense if filtered_dense else dense

            for d in use_dense:
                text = d["doc"]["text"]
                dense_score = d["score"]
                hybrid_score = (1 - self.alpha) * dense_score
                results.append(
                    RetrievedDoc(
                        text=text,
                        metadata={k: v for k, v in d["doc"].items() if k != "text"},
                        hybrid_score=hybrid_score,
                        sparse_score=0.0,
                        dense_score=dense_score,
                    )
                )

        results.sort(key=lambda x: x.hybrid_score, reverse=True)
        return results[:k]
