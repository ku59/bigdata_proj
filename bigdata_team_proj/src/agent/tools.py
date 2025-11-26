from typing import Any, Dict, List

from src.data_ingestion.dart_client import DartClient
from src.data_ingestion.dart_parsers import normalize_finstat_rows
from src.data_ingestion.news_client import NaverNewsClient
from src.retrieval.hybrid_retriever import HybridRetriever


def tool_get_latest_finstat(corp_code: str, year: str) -> Dict[str, Any]:
    dart = DartClient()
    fin = dart.get_finstat(corp_code=corp_code, bsns_year=year)
    rows = fin.get("list", [])
    return normalize_finstat_rows(rows)


def tool_search_news(corp_name: str, limit: int = 10) -> List[Dict[str, Any]]:
    client = NaverNewsClient()
    items = client.search(query=corp_name, display=limit)
    return items


def tool_hybrid_search(query: str, k: int = 8) -> List[Dict[str, Any]]:
    retriever = HybridRetriever(alpha=0.6)
    docs = retriever.retrieve(query, k=k)
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

