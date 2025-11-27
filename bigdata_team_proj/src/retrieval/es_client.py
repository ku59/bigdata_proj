from typing import Any, Dict, Iterable, List

from elasticsearch import Elasticsearch
import logging

from src.utils.settings import settings


class ESClient:
    def __init__(self, host: str | None = None) -> None:
        self.es = Elasticsearch(hosts=[host or settings.ELASTICSEARCH_HOST])
        self.index = settings.ELASTICSEARCH_INDEX

    def create_index(self) -> None:
        if self.es.indices.exists(index=self.index):
            return
        mapping: Dict[str, Any] = {
            "mappings": {
                "properties": {
                    "text": {"type": "text"},
                    "company_code": {"type": "keyword"},
                    "stock_code": {"type": "keyword"},
                    "company_name": {"type": "keyword"},
                    "source": {"type": "keyword"},
                    "year": {"type": "keyword"},
                    "pub_date": {"type": "date", "format": "EEE, dd MMM yyyy HH:mm:ss Z||strict_date_optional_time"},
                }
            }
        }
        self.es.indices.create(index=self.index, body=mapping)

    def bulk_index(self, docs: Iterable[Dict[str, Any]]) -> None:
        from elasticsearch.helpers import bulk

        actions = (
            {
                "_index": self.index,
                "_source": doc,
            }
            for doc in docs
        )
        bulk(self.es, actions)

    def search(
        self,
        query: str,
        size: int = 20,
        corp_code: str | None = None,
        stock_code: str | None = None,
        year: str | None = None,
    ) -> List[Dict[str, Any]]:
        """
        회사 코드와 연도 기반으로 검색을 강화한다.
        - corp_code: DART 공시 고유코드(예: 00126380)
        - stock_code: 주식 코드(예: 005930)
        - year: 문서 연도(예: "2024")
        corp_code/stock_code가 주어지면 OR 필터(should, minimum_should_match=1)로 제한한다.
        year가 주어지면 추가 term 필터로 연도를 제한한다.
        """
        base_query = {
            "multi_match": {
                "query": query,
                "fields": ["text", "company_name^2"],
            }
        }

        bool_query: Dict[str, Any] = {"must": base_query}
        filters: List[Dict[str, Any]] = []

        # 회사 코드 OR 필터
        should_terms: List[Dict[str, Any]] = []
        if corp_code:
            should_terms.append({"term": {"company_code": corp_code}})
        if stock_code:
            should_terms.append({"term": {"stock_code": stock_code}})
        if should_terms:
            filters.append(
                {
                    "bool": {
                        "should": should_terms,
                        "minimum_should_match": 1,
                    }
                }
            )

        # 연도 필터
        if year:
            filters.append({"term": {"year": year}})

        if filters:
            bool_query["filter"] = filters

        body = {"query": {"bool": bool_query}}

        try:
            res = self.es.search(index=self.index, body=body, size=size)
            hits = res["hits"]["hits"]
            return [
                {
                    "score": h["_score"],
                    "doc": h["_source"],
                }
                for h in hits
            ]
        except Exception as e:
            logging.getLogger(__name__).warning("Elasticsearch search failed: %s", e)
            return []
