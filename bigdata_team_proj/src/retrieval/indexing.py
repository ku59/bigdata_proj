import json
from pathlib import Path
from typing import Dict, List

from src.retrieval.es_client import ESClient
from src.retrieval.vectorstore import VectorStore
from src.utils.logging_utils import configure_logging

DATA_DIR = Path("data") / "processed"


def load_corpus(path: Path) -> List[Dict]:
    docs: List[Dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            docs.append(json.loads(line))
    return docs


def main() -> None:
    configure_logging()
    es = ESClient()
    vs = VectorStore()

    corpus_path = DATA_DIR / "corpus.jsonl"
    docs = load_corpus(corpus_path)

    es.create_index()
    es.bulk_index(docs)
    vs.index_docs(docs)

    print(f"Indexed {len(docs)} docs into ES & VectorStore")


if __name__ == "__main__":
    main()

