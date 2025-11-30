from typing import Any, Dict, Iterable, List, Sequence

from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk
import logging

from src.utils.settings import settings

logger = logging.getLogger(__name__)


class ESClient:
    def __init__(
        self,
        host: str | None = None,
        index: str | None = None,
        indices: list[str] | None = None,
    ) -> None:
        # Elastic Cloud에 API Key로 접속
        self.es = Elasticsearch(
            host or settings.ELASTICSEARCH_HOST,
            api_key=settings.ELASTICSEARCH_API_KEY,
        )
        # 쓰기용 기본 인덱스(예: 뉴스)
        self.index = index or settings.ELASTICSEARCH_NEWS_INDEX
        # 조회용 기본 인덱스(뉴스 + 재무제표 둘 다)
        self.search_indices = indices or [
            settings.ELASTICSEARCH_NEWS_INDEX,
            settings.ELASTICSEARCH_FINSTAT_INDEX,
        ]

    def create_index(self) -> None:
        # 단일 인덱스(self.index)에 대해서만 매핑 생성
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
                    "pub_date": {
                        "type": "date",
                        "format": "EEE, dd MMM yyyy HH:mm:ss Z||strict_date_optional_time",
                    },
                    "embedding": {
                        "type": "dense_vector",
                        "dims": 384,
                        "index": True,
                        "similarity": "cosine",
                    },
                }
            }
        }

        self.es.indices.create(index=self.index, body=mapping)

    def bulk_index(self, docs: Iterable[Dict[str, Any]]) -> None:
        """
        self.index(단일 인덱스)에 bulk 적재.
        """
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
        BM25 기반 sparse 검색.
        기본적으로 news_index + finstat_index 두 인덱스를 모두 검색.
        """
        base_query: Dict[str, Any] = {
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
            # 두 인덱스를 동시에 검색
            res = self.es.search(index=self.search_indices, body=body, size=size)
            hits = res["hits"]["hits"]
            return [
                {
                    "score": h["_score"],
                    "doc": h["_source"],
                }
                for h in hits
            ]
        except Exception as e:
            logger.warning("Elasticsearch search failed: %s", e)
            return []

    def knn_search(
        self,
        query_vector: Sequence[float],
        size: int = 20,
        corp_code: str | None = None,
        stock_code: str | None = None,
        year: str | None = None,
    ) -> List[Dict[str, Any]]:
        """
        embedding 필드를 이용한 k-NN dense 검색.
        기본적으로 news_index + finstat_index 두 인덱스를 모두 검색.
        """
        filters: List[Dict[str, Any]] = []

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

        if year:
            filters.append({"term": {"year": year}})

        if filters:
            query_part: Dict[str, Any] = {"bool": {"filter": filters}}
        else:
            query_part = {"match_all": {}}

        body = {
            "knn": {
                "field": "embedding",
                "query_vector": query_vector,
                "k": size,
                "num_candidates": max(size * 10, 100),
            },
            "query": query_part,
        }

        try:
            res = self.es.search(index=self.search_indices, body=body, size=size)
            hits = res["hits"]["hits"]
            return [
                {
                    "score": h["_score"],
                    "doc": h["_source"],
                }
                for h in hits
            ]
        except Exception as e:
            logger.warning("Elasticsearch knn_search failed: %s", e)
            return []

