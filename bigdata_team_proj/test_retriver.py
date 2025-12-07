from src.retrieval.hybrid_retriever import HybridRetriever

hr = HybridRetriever(alpha=0.6)
docs = hr.retrieve("삼성전자 실적 알려줘", k=5, corp_code=None, stock_code=None, year=None)
print(len(docs))
for d in docs:
    print(d.text[:100])
