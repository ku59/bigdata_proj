import json
import os
import zipfile
import xml.etree.ElementTree as ET
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import logging
import requests
from tqdm import tqdm
from dotenv import load_dotenv  # .env 파일에서 환경변수 로드[web:74]

from src.data_ingestion.dart_client import DartClient
from src.data_ingestion.dart_parsers import normalize_finstat_rows
from src.data_ingestion.news_client import NaverNewsClient
from src.utils.logging_utils import configure_logging

DATA_DIR = Path("data")
PROCESSED_DIR = DATA_DIR / "processed"
META_DIR = DATA_DIR / "meta"

PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
META_DIR.mkdir(parents=True, exist_ok=True)

# DART 고유번호 API (corpCode.xml)[web:40][web:48]
DART_CORP_CODE_API = "https://opendart.fss.or.kr/api/corpCode.xml"

# 환경변수 키 이름
DART_API_KEY_ENV = "DART_API_KEY"

logger = logging.getLogger(__name__)


def fetch_corp_code_xml_bytes(api_key: str) -> bytes:
    """
    OpenDART corpCode.xml API를 호출하여 ZIP 바이트를 가져온다.[web:40][web:46]
    """
    params = {"crtfc_key": api_key}
    resp = requests.get(DART_CORP_CODE_API, params=params, timeout=30)
    resp.raise_for_status()
    return resp.content


def parse_corp_list_from_zip(zip_bytes: bytes) -> List[Tuple[str, str, str]]:
    """
    corpCode.zip 내용(CORPCODE.xml)을 파싱해서
    (corp_code, corp_name, stock_code) 리스트를 만든다.[web:40][web:46]
    """
    with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
        xml_name = None
        for name in zf.namelist():
            if name.lower().endswith(".xml"):
                xml_name = name
                break
        if xml_name is None:
            raise RuntimeError("XML 파일을 ZIP 안에서 찾지 못했습니다.")

        with zf.open(xml_name) as f:
            xml_bytes = f.read()

    root = ET.fromstring(xml_bytes.decode("utf-8"))

    result: List[Tuple[str, str, str]] = []
    for corp in root.findall("list"):
        corp_code = (corp.findtext("corp_code") or "").strip()
        corp_name = (corp.findtext("corp_name") or "").strip()
        stock_code = (corp.findtext("stock_code") or "").strip()
        result.append((corp_code, corp_name, stock_code))

    return result


def build_corp_list_from_dart(
    api_key: str,
    cache_path: Path = META_DIR / "corp_list.json",
    use_cache: bool = True,
    only_listed: bool = True,
    max_companies: Optional[int] = None,
) -> List[Tuple[str, str]]:
    """
    DART에서 공시대상회사 전체를 받아와서 (corp_code, corp_name) 리스트로 변환.

    - only_listed=True: 종목코드(stock_code)가 있는 회사만 사용 (상장사 기준).[web:40][web:51]
    - max_companies: 지정 시 상위 N개만 사용 (개발/테스트용).
    """
    if use_cache and cache_path.exists():
        logger.info("Loading corp_list from cache: %s", cache_path)
        with cache_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return [(item["corp_code"], item["corp_name"]) for item in data]

    logger.info("Fetching corpCode.xml from OpenDART...")
    zip_bytes = fetch_corp_code_xml_bytes(api_key)
    corp_raw_list = parse_corp_list_from_zip(zip_bytes)

    filtered: List[Tuple[str, str]] = []
    for corp_code, corp_name, stock_code in corp_raw_list:
        if only_listed and not stock_code:
            continue
        filtered.append((corp_code, corp_name))

    # 중복 제거 (corp_code 기준)
    seen = set()
    unique_list: List[Tuple[str, str]] = []
    for corp_code, corp_name in filtered:
        if corp_code in seen:
            continue
        seen.add(corp_code)
        unique_list.append((corp_code, corp_name))

    if max_companies is not None:
        unique_list = unique_list[:max_companies]

    cache_items = [
        {"corp_code": c, "corp_name": n}
        for c, n in unique_list
    ]
    with cache_path.open("w", encoding="utf-8") as f:
        json.dump(cache_items, f, ensure_ascii=False, indent=2)

    logger.info("Saved %d corp entries to cache: %s", len(unique_list), cache_path)
    return unique_list


def build_company_corpus(corp_code: str, corp_name: str) -> List[Dict]:
    """
    한 기업에 대해 재무제표 요약 + 뉴스 요약을 수집.
    """
    dart = DartClient()
    naver = NaverNewsClient()

    reports = dart.list_reports(corp_code=corp_code, bgn_de="20200101")
    corpus: List[Dict] = []

    # 1) 재무제표 요약
    for r in tqdm(reports, desc=f"DART reports ({corp_name})"):
        rpt_nm = r.get("rpt_nm", "")
        year = rpt_nm[:4]

        if not year.isdigit():
            continue

        fin = dart.get_finstat(corp_code=corp_code, bsns_year=year)
        rows = fin.get("list", [])
        if not rows:
            continue

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
    for item in tqdm(news_items, desc=f"Naver news ({corp_name})"):
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
    # 1) 로깅 설정
    configure_logging()

    # 2) .env 로드 (현재/상위 디렉터리의 .env를 자동 탐색)[web:74][web:83]
    load_dotenv()

    # 3) 환경변수에서 DART API 키 읽기
    api_key = os.getenv(DART_API_KEY_ENV)
    if not api_key:
        raise RuntimeError(
            f"{DART_API_KEY_ENV} 환경변수가 설정되지 않았습니다. "
            f".env 파일에 {DART_API_KEY_ENV}=... 형식으로 넣었는지 확인하세요."
        )

    # 4) DART에서 상장사 리스트 로딩 (캐시 사용)
    corp_list = build_corp_list_from_dart(
        api_key=api_key,
        cache_path=META_DIR / "corp_list.json",
        use_cache=True,
        only_listed=True,
        max_companies=None,  # 개발 중에는 100 등으로 제한 가능
    )

    logger.info("Total companies to process: %d", len(corp_list))

    all_docs: List[Dict] = []

    for corp_code, corp_name in tqdm(corp_list, desc="Companies"):
        try:
            docs = build_company_corpus(corp_code, corp_name)
            all_docs.extend(docs)
        except Exception as e:
            logger.exception("Error processing %s %s: %s", corp_code, corp_name, e)

    out_path = PROCESSED_DIR / "corpus.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for doc in all_docs:
            f.write(json.dumps(doc, ensure_ascii=False) + "\n")

    logger.info("Saved %d docs to %s", len(all_docs), out_path)


if __name__ == "__main__":
    main()

