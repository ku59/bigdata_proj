import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
import html

import requests

from src.utils.settings import settings

logger = logging.getLogger(__name__)


def _strip_html(text: Optional[str]) -> str:
    """HTML 태그 제거 + 엔티티 언이스케이프(단순화)."""
    if not text:
        return ""
    # Remove simple <b> tag and any HTML tags
    s = re.sub(r"<[^>]+>", " ", text)
    # Unescape common HTML entities safely
    s = html.unescape(s)
    # Normalize whitespaces
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _normalize_title(title: Optional[str]) -> str:
    """중복 판정을 위한 제목 정규화(소문자, 괄호/대괄호 내용 제거, 특수문자 제거)."""
    t = _strip_html(title)
    # Remove contents in brackets () [] {} to avoid noisy tokens like [단독], (영상)
    t = re.sub(r"[\(\[\{].*?[\)\]\}]", " ", t)
    # Keep word characters and Korean letters only
    t = re.sub(r"[^\w\s가-힣]", " ", t)
    # Collapse spaces and lower
    t = re.sub(r"\s+", " ", t).strip().lower()
    return t


def _canonical_url(u: Optional[str]) -> Optional[str]:
    """쿼리/프래그먼트 제거한 정규 URL 생성. 모바일 서브도메인(m.) 제거."""
    if not u:
        return None
    try:
        p = urlparse(u)
        scheme = p.scheme or "https"
        netloc = (p.netloc or "").lower()
        if netloc.startswith("m."):
            netloc = netloc[2:]
        path = p.path or "/"
        return f"{scheme}://{netloc}{path}"
    except Exception:
        return None


def _pick_latest(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """중복 그룹에서 최신(pubDate) 1건 선택."""
    def _key(it: Dict[str, Any]) -> str:
        return str(it.get("pubDate", ""))
    return sorted(items, key=_key, reverse=True)[0]


class NaverNewsClient:
    BASE_URL = "https://openapi.naver.com/v1/search/news.json"

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
    ) -> None:
        self.client_id = client_id or settings.NAVER_CLIENT_ID
        self.client_secret = client_secret or settings.NAVER_CLIENT_SECRET

    def _headers(self) -> Dict[str, str]:
        return {
            "X-Naver-Client-Id": self.client_id,
            "X-Naver-Client-Secret": self.client_secret,
        }

    def search(
        self,
        query: str,
        display: int = 20,
        start: int = 1,
        sort: str = "sim",  # "sim" | "date"
    ) -> List[Dict[str, Any]]:
        """네이버 뉴스 원본 검색 결과 반환(가공 없음)."""
        params = {
            "query": query,
            "display": display,
            "start": start,
            "sort": sort,
        }
        resp = requests.get(self.BASE_URL, headers=self._headers(), params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data.get("items", []) or []

    def search_dedup(
        self,
        query: str,
        display: int = 20,
        start: int = 1,
        sort: str = "sim",               # "sim" | "date"
        dedup_strength: str = "medium",  # 인터페이스 유지(내부는 단순 처리)
    ) -> List[Dict[str, Any]]:
        """
        간단한 중복 제거 버전:
        1) canonical_url 기준으로 중복 그룹화
        2) canonical_url 없으면 normalized title 기준으로 그룹화
        3) 각 그룹에서 pubDate 최신 1건 선택
        4) UI 편의 필드(title_norm, description_clean, canonical_url) 추가
        """
        items = self.search(query=query, display=display, start=start, sort=sort)
        if not items:
            return []

        buckets: Dict[str, List[Dict[str, Any]]] = {}
        for it in items:
            canon = _canonical_url(it.get("originallink")) or _canonical_url(it.get("link"))
            key = canon if canon else f"title::{_normalize_title(it.get('title', ''))}"
            buckets.setdefault(key, []).append(it)

        deduped: List[Dict[str, Any]] = []
        for _, group in buckets.items():
            deduped.append(_pick_latest(group))

        # 정렬: sort=date면 pubDate 내림차순, sim이면 원래 순서 유지
        if sort == "date":
            deduped = sorted(deduped, key=lambda it: str(it.get("pubDate", "")), reverse=True)

        # UI 필드 보강
        for it in deduped:
            it["title_norm"] = _normalize_title(it.get("title", ""))
            it["description_clean"] = _strip_html(it.get("description", ""))
            it["canonical_url"] = _canonical_url(it.get("originallink")) or _canonical_url(it.get("link"))

        return deduped
