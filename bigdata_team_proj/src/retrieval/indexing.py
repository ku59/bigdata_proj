import json
from pathlib import Path
from typing import Dict, List

from sentence_transformers import SentenceTransformer

from src.retrieval.es_client import ESClient
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
    encoder = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

    corpus_path = DATA_DIR / "corpus.jsonl"
    docs = load_corpus(corpus_path)

    # 텍스트 임베딩 계산 후 문서에 embedding 필드로 추가
    texts = [d.get("text", "") for d in docs]
    vectors = encoder.encode(texts, show_progress_bar=True)

    for doc, vec in zip(docs, vectors):
        doc["embedding"] = vec.tolist()

    es.create_index()
    es.bulk_index(docs)

    print(f"Indexed {len(docs)} docs into ES (with embeddings)")


if __name__ == "__main__":
    main()

