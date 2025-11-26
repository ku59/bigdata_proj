import json
from pathlib import Path
from typing import Dict, List

from tqdm import tqdm

from src.data_ingestion.dart_client import DartClient
from src.data_ingestion.dart_parsers import normalize_finstat_rows
from src.data_ingestion.news_client import NaverNewsClient
from src.utils.logging_utils import configure_logging

DATA_DIR = Path("data")
PROCESSED_DIR = DATA_DIR / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


def build_company_corpus(corp_code: str, corp_name: str) -> List[Dict]:
    dart = DartClient()
    naver = NaverNewsClient()

    reports = dart.list_reports(corp_code=corp_code, bgn_de="20190101")
    corpus: List[Dict] = []

    # 1) 재무제표 요약
    for r in tqdm(reports, desc="DART reports"):
        year = r.get("rpt_nm", "")[:4]  # 간단 예시
        fin = dart.get_finstat(corp_code=corp_code, bsns_year=year)
        rows = fin.get("list", [])
        summary = normalize_finstat_rows(rows)

        text = (
            f"{corp_name} {year}년 재무 요약. "
            f"자산 {summary['assets']}, 부채 {summary['liabilities']}, "
            f"자본 {summary['equity']}, 매출 {summary['revenue']}, "
            f"영업이익 {summary['operating_income']}, 순이익 {summary['net_income']}."
        )

        corpus.append(
            {
                "company_code": corp_code,
                "company_name": corp_name,
                "year": year,
                "source": "dart_finstat",
                "text": text,
                "raw": summary,
            }
        )

    # 2) 뉴스 요약
    news_items = naver.search(query=corp_name, display=50)
    for item in tqdm(news_items, desc="Naver news"):
        text = f"{corp_name} 관련 뉴스 제목: {item['title']}. 요약: {item['description']}"
        corpus.append(
            {
                "company_code": corp_code,
                "company_name": corp_name,
                "source": "naver_news",
                "link": item.get("link"),
                "pub_date": item.get("pubDate"),
                "text": text,
                "raw": item,
            }
        )

    return corpus


def main() -> None:
    configure_logging()

    corp_list = [("005930", "삼성전자")]  # 데모용. 실제로는 CSV/DB 등에서 로딩.
    all_docs: List[Dict] = []

    for corp_code, corp_name in corp_list:
        all_docs.extend(build_company_corpus(corp_code, corp_name))

    out_path = PROCESSED_DIR / "corpus.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for doc in all_docs:
            f.write(json.dumps(doc, ensure_ascii=False) + "\n")

    print(f"Saved {len(all_docs)} docs to {out_path}")


if __name__ == "__main__":
    main()

