from typing import Any, Dict, Iterable, List

from elasticsearch import Elasticsearch

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

    def search(self, query: str, size: int = 20) -> List[Dict[str, Any]]:
        body = {
            "query": {
                "multi_match": {
                    "query": query,
                    "fields": ["text", "company_name^2"],
                }
            }
        }
        res = self.es.search(index=self.index, body=body, size=size)
        hits = res["hits"]["hits"]
        return [
            {
                "score": h["_score"],
                "doc": h["_source"],
            }
            for h in hits
        ]

