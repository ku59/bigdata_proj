import logging
from typing import Any, Dict, List, Optional

import requests

from src.utils.settings import settings

logger = logging.getLogger(__name__)


class DartClient:
    BASE_URL = "https://opendart.fss.or.kr/api"

    def __init__(self, api_key: Optional[str] = None) -> None:
        # .env → settings.DART_API_KEY 에서 키를 읽어옴
        self.api_key = api_key or settings.DART_API_KEY

    def _get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        DART 공통 GET 요청 함수.
        - crtfc_key 자동 추가
        - HTTP 에러 raise
        - status != '000' 이면 warning 로그
        """
        params = {"crtfc_key": self.api_key, **params}
        url = f"{self.BASE_URL}/{path}"
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()

        data = resp.json()
        if data.get("status") != "000":
            logger.warning("DART API error: %s", data.get("message"))
        return data

    def list_reports(
        self,
        corp_code: str,
        bgn_de: str = "20190101",
        end_de: str = "",
        page_count: int = 100,
        regular_only: bool = False,  #정기공시(사업/반기/분기)만 볼지 여부
    ) -> List[Dict[str, Any]]:
        """
        공시 목록 조회.

        - regular_only=False:
            → 필터 없이 해당 회사 공시를 그대로 반환
        - regular_only=True:
            → 정기공시(pblntf_ty='A') 중에서
               사업(A001) / 반기(A002) / 분기(A003) 보고서만 모아서 반환
        """
        # 공통 파라미터 (정기/비정기 공통)
        base_params: Dict[str, Any] = {
            "corp_code": corp_code,
            "bgn_de": bgn_de,
            "end_de": end_de,
            "page_count": page_count,
        }

        # 1) regular_only=False : 한 번만 호출
        if not regular_only:
            data = self._get("list.json", base_params)
            return data.get("list", []) or []

        # 2) regular_only=True : 정기공시 A001/A002/A003만 모아서 반환
        detail_codes = ["A001", "A002", "A003"]  # 사업, 반기, 분기
        all_rows: List[Dict[str, Any]] = []

        for detail in detail_codes:
            params = {
                **base_params,
                "pblntf_ty": "A",         # 정기공시
                "pblntf_detail_ty": detail,  # A001/A002/A003 중 하나
            }
            data = self._get("list.json", params)
            rows = data.get("list", []) or []
            all_rows.extend(rows)

        # rcept_no 기준으로 중복 제거 (같은 보고서가 겹칠 가능성 대비)
        dedup: Dict[str, Dict[str, Any]] = {}
        for row in all_rows:
            rcept_no = row.get("rcept_no")
            if not rcept_no:
                continue
            dedup[rcept_no] = row

        # 접수일자 기준 내림차순 정렬
        sorted_rows = sorted(
            dedup.values(),
            key=lambda x: x.get("rcept_dt", ""),
            reverse=True,
        )

        return list(sorted_rows)

    def get_finstat(
        self,
        corp_code: str,
        bsns_year: str,
        reprt_code: str = "11011",  # 사업보고서
        fs_div: str = "CFS",        # CFS=연결, OFS=개별
    ) -> Dict[str, Any]:
        """단일회사 전체 재무제표 조회."""
        params = {
            "corp_code": corp_code,
            "bsns_year": bsns_year,
            "reprt_code": reprt_code,
            "fs_div": fs_div,
        }
        return self._get("fnlttSinglAcntAll.json", params)
