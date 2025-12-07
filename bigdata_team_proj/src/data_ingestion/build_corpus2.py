import json
import os
import zipfile
import xml.etree.ElementTree as ET
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import requests
from tqdm import tqdm

from src.data_ingestion.dart_client import DartClient
from src.data_ingestion.dart_parsers import normalize_finstat_rows
from src.data_ingestion.news_client import NaverNewsClient
from src.utils.logging_utils import configure_logging, get_logger  # get_logger는 있으면 사용, 없으면 logging.getLogger로 대체

DATA_DIR = Path("data")
PROCESSED_DIR = DATA_DIR / "processed"
META_DIR = DATA_DIR / "meta"

PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
META_DIR.mkdir(parents=True, exist_ok=True)

# DART 고유번호 API (corpCode.xml) 엔드포인트[web:40][web:48]
DART_CORP_CODE_API = "https://opendart.fss.or.kr/api/corpCode.xml"

# 환경변수에서 DART API 키 읽기 (또는 .env / 설정파일 등)
DART_API_KEY_ENV = "DART_API_KEY"

logger = get_logger(__name__) if "get_logger" in globals() else None


def log_info(msg: str) -> None:
    if logger:
        logger.info(msg)
    else:
        print(msg)


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
    corpCode.zip 내용(CORPCODE.xml)을 파싱해서 (corp_code, corp_name, stock_code) 리스트를 만든다.[web:40][web:46]
    """
    with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
        # 보통 파일명이 "CORPCODE.xml" 한 개 들어있음.[web:40]
        xml_name = None
        for name in zf.namelist():
            if name.lower().endswith(".xml"):
                xml_name = name
                break
        if xml_name is None:
            raise RuntimeError("XML 파일을 ZIP 안에서 찾지 못했습니다.")

        with zf.open(xml_name) as f:
            xml_bytes = f.read()

    # 인코딩은 UTF-8로 명시되어 있음.[web:40]
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
    DART에서 공시대상회사 전체를 받아와서
    (corp_code, corp_name) 리스트로 변환한다.

    - only_listed=True 이면 종목코드(stock_code)가 있는 회사만 사용 (상장사 기준).[web:40][web:51]
    - max_companies가 지정되면 상위 N개만 사용 (개발/테스트용).
    결과는 캐시에 JSON으로 저장하여 재사용한다.
    """
    if use_cache and cache_path.exists():
        log_info(f"Loading corp_list from cache: {cache_path}")
        with cache_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return [(item["corp_code"], item["corp_name"]) for item in data]

    log_info("Fetching corpCode.xml from OpenDART...")
    zip_bytes = fetch_corp_code_xml_bytes(api_key)
    corp_raw_list = parse_corp_list_from_zip(zip_bytes)

    # 상장사만 필터링 (stock_code != "")[web:40][web:51]
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

    # 캐시 저장
    cache_items = [
        {"corp_code": c, "corp_name": n}
        for c, n in unique_list
    ]
    with cache_path.open("w", encoding="utf-8") as f:
        json.dump(cache_items, f, ensure_ascii=False, indent=2)

    log_info(f"Saved {len(unique_list)} corp entries to cache: {cache_path}")
    return unique_list


def build_company_corpus(corp_code: str, corp_name: str) -> List[Dict]:
    """
    기존에 사용하던 build_company_corpus를 그대로 사용.
    - 재무제표 요약 (연도별)
    - 네이버 뉴스 요약
    """
    dart = DartClient()
    naver = NaverNewsClient()

    reports = dart.list_reports(corp_code=corp_code, bgn_de="20190101")
    corpus: List[Dict] = []

    # 1) 재무제표 요약
    for r in tqdm(reports, desc=f"DART reports ({corp_name})"):
        rpt_nm = r.get("rpt_nm", "")
        year = rpt_nm[:4]

        # 연도 추출 실패 시 스킵
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
    configure_logging()

    api_key = os.getenv(DART_API_KEY_ENV)
    if not api_key:
        raise RuntimeError(
            f"{DART_API_KEY_ENV} 환경변수가 설정되지 않았습니다. "
            f"OpenDART에서 발급받은 API 키를 {DART_API_KEY_ENV}에 넣어주세요."
        )

    # 서비스에서는 use_cache=True + only_listed=True를 기본으로 두고,
    # max_companies는 설정/CLI로 제어 (없으면 전체 상장사 대상).[web:40][web:51]
    corp_list = build_corp_list_from_dart(
        api_key=api_key,
        cache_path=META_DIR / "corp_list.json",
        use_cache=True,
        only_listed=True,
        max_companies=None,  # 예: 개발 중에는 100 정도로 제한
    )

    log_info(f"Total companies to process: {len(corp_list)}")

    all_docs: List[Dict] = []

    for corp_code, corp_name in tqdm(corp_list, desc="Companies"):
        try:
            docs = build_company_corpus(corp_code, corp_name)
            all_docs.extend(docs)
        except Exception as e:
            # 개별 기업 에러는 로그만 남기고 계속 진행
            if logger:
                logger.exception(f"Error processing {corp_code} {corp_name}: {e}")
            else:
                print(f"Error processing {corp_code} {corp_name}: {e}")

    out_path = PROCESSED_DIR / "corpus.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for doc in all_docs:
            f.write(json.dumps(doc, ensure_ascii=False) + "\n")

    log_info(f"Saved {len(all_docs)} docs to {out_path}")


if __name__ == "__main__":
    main()

