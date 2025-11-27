from typing import Any, Dict, List, Optional

from src.data_ingestion.dart_client import DartClient
from src.data_ingestion.dart_parsers import normalize_finstat_rows
from src.data_ingestion.news_client import NaverNewsClient
from src.retrieval.hybrid_retriever import HybridRetriever


def tool_get_latest_finstat(
    corp_code: str,
    year: str,
    reprt_code: str = "11011",  # 기본: 사업보고서
    fs_div: str = "CFS",        # 기본: 연결
) -> Dict[str, Any]:
    """
    단일 연도/보고서 기준 재무 요약(th) 반환.
    기존 함수와 동일 목적이나 reprt_code/fs_div 선택 가능하도록 확장.
    """
    dart = DartClient()
    fin = dart.get_finstat(corp_code=corp_code, bsns_year=year, reprt_code=reprt_code, fs_div=fs_div)
    rows = fin.get("list", [])
    return normalize_finstat_rows(rows)


def tool_get_finstat_bulk(
    corp_code: str,
    years: List[str],
    reprt_codes: List[str],
    fs_div: str = "CFS",
) -> List[Dict[str, Any]]:
    """
    멀티 연도 × 멀티 보고서 코드 조합으로 재무 요약 리스트를 반환.
    각 항목은 {"year": y, "reprt_code": rc, **normalize_finstat_rows(rows)} 형태.
    """
    dart = DartClient()
    results: List[Dict[str, Any]] = []

    for y in years:
        for rc in reprt_codes:
            try:
                fin = dart.get_finstat(corp_code=corp_code, bsns_year=y, reprt_code=rc, fs_div=fs_div)
                rows = fin.get("list", [])
                summary = normalize_finstat_rows(rows)
                # 모든 지표가 None인 경우는 제외(빈 데이터 방지)
                metrics_keys = ["assets", "liabilities", "equity", "revenue", "operating_income", "net_income"]
                if any(summary.get(k) is not None for k in metrics_keys):
                    results.append({"year": y, "reprt_code": rc, **summary})
            except Exception:
                # 개별 실패는 무시하고 계속 진행
                continue

    return results


def tool_search_news(
    corp_name: str,
    limit: int = 10,
    sort: str = "sim",                 # "sim" | "date"
    dedup_strength: str = "medium",    # "low" | "medium" | "high"
    start: int = 1,
) -> List[Dict[str, Any]]:
    """
    네이버 뉴스 검색(중복 제거 포함).
    기존 단순 검색을 중복 제거(search_dedup)로 대체하고 파라미터 확장.
    """
    client = NaverNewsClient()
    items = client.search_dedup(
        query=corp_name,
        display=limit,
        start=start,
        sort=sort,
        dedup_strength=dedup_strength,
    )
    return items


def tool_hybrid_search(
    query: str,
    k: int = 8,
    corp_code: Optional[str] = None,
    stock_code: Optional[str] = None,
    year: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    하이브리드 검색(ES + 벡터) 수행.
    - corp_code: DART 공시 고유코드(예: 00126380)
    - stock_code: 주식 코드(예: 005930)
    - year: 문서 연도(예: '2024')
    회사 코드(둘 중 하나)와 연도를 전달하면 ES 필터 및 VS 메타 필터로 해당 회사/연도 근거를 우선 확보한다.
    """
    retriever = HybridRetriever(alpha=0.6)
    docs = retriever.retrieve(query, k=k, corp_code=corp_code, stock_code=stock_code, year=year)
    return [
        {
            "text": d.text,
            "metadata": d.metadata,
            "hybrid_score": d.hybrid_score,
            "sparse_score": d.sparse_score,
            "dense_score": d.dense_score,
        }
        for d in docs
    ]
