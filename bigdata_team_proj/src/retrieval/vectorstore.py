from pathlib import Path
from typing import Any, Dict, List

import chromadb
from chromadb.config import Settings as ChromaSettings
from sentence_transformers import SentenceTransformer

from src.utils.settings import settings


class VectorStore:
    def __init__(self) -> None:
        persist_dir = Path(settings.VECTOR_DB_DIR)
        persist_dir.mkdir(parents=True, exist_ok=True)

        self.client = chromadb.PersistentClient(
            path=str(persist_dir),
            settings=ChromaSettings(allow_reset=True),
        )
        self.collection = self.client.get_or_create_collection("company_corpus")
        self.encoder = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

    def index_docs(self, docs: List[Dict[str, Any]]) -> None:
        texts = [d["text"] for d in docs]
        ids = [str(i) for i in range(len(texts))]
        embeddings = self.encoder.encode(texts, show_progress_bar=True)
        metadatas = [
            {k: v for k, v in d.items() if k != "text"}
            for d in docs
        ]
        self.collection.add(ids=ids, documents=texts, embeddings=embeddings, metadatas=metadatas)

    def search(self, query: str, k: int = 20) -> List[Dict[str, Any]]:
        emb = self.encoder.encode([query])[0]
        res = self.collection.query(
            query_embeddings=[emb],
            n_results=k,
        )
        results: List[Dict[str, Any]] = []
        for doc, meta, dist in zip(
            res.get("documents", [[]])[0],
            res.get("metadatas", [[]])[0],
            res.get("distances", [[]])[0],
        ):
            results.append(
                {
                    "score": 1.0 - dist,  # cosine distance -> similarity 대략 변환
                    "doc": {**meta, "text": doc},
                }
            )
        return results

