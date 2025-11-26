import logging
from typing import Any, Dict, List, Optional

import requests

from src.utils.settings import settings

logger = logging.getLogger(__name__)


class NaverNewsClient:
    BASE_URL = "https://openapi.naver.com/v1/search/news.json"

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
    ) -> None:
        self.client_id = client_id or settings.NAVER_CLIENT_ID
        self.client_secret = client_secret or settings.NAVER_CLIENT_SECRET

    def search(
        self,
        query: str,
        display: int = 20,
        start: int = 1,
        sort: str = "sim",
    ) -> List[Dict[str, Any]]:
        headers = {
            "X-Naver-Client-Id": self.client_id,
            "X-Naver-Client-Secret": self.client_secret,
        }
        params = {
            "query": query,
            "display": display,
            "start": start,
            "sort": sort,
        }
        resp = requests.get(self.BASE_URL, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data.get("items", [])

