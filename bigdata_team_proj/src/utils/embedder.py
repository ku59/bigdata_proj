from sentence_transformers import SentenceTransformer

class Embedder:
    """
    Sentence-BERT 임베딩 래퍼.
    """
    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        self.model = SentenceTransformer(model_name)

    def embed(self, texts):
        """
        문자열 리스트 -> 벡터 리스트
        """
        return self.model.encode(texts, convert_to_numpy=False)
