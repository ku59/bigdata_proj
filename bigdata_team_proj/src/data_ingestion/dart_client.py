import logging
from typing import Any, Dict, List, Optional

import requests

from src.utils.settings import settings

logger = logging.getLogger(__name__)


class DartClient:
    BASE_URL = "https://opendart.fss.or.kr/api"

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or settings.DART_API_KEY

    def _get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
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
    ) -> List[Dict[str, Any]]:
        """공시 목록 조회 (사업/반기/분기 보고서 위주)."""
        params = {
            "corp_code": corp_code,
            "bgn_de": bgn_de,
            "end_de": end_de,
            "page_count": page_count,
        }
        data = self._get("list.json", params)
        return data.get("list", [])

    def get_finstat(
        self,
        corp_code: str,
        bsns_year: str,
        reprt_code: str = "11011",  # 사업보고서
    ) -> Dict[str, Any]:
        """주요 재무제표 항목 조회."""
        params = {
            "corp_code": corp_code,
            "bsns_year": bsns_year,
            "reprt_code": reprt_code,
        }
        return self._get("fnlttSinglAcntAll.json", params)

