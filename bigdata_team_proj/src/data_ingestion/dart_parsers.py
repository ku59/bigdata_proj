# src/data_ingestion/dart_parsers.py
"""
DART 재무제표(fnlttSinglAcntAll) 결과에서
핵심 지표(자산/부채/자본/매출/영업이익/당기순이익)를 뽑아서 표준화하고,
ES / 벡터 DB에 넣기 좋은 문서 형태로 변환하는 모듈.
"""

from typing import Any, Dict, List, Optional


# -----------------------------
# 내부 유틸 함수
# -----------------------------
def _parse_int(amount: Any) -> Optional[int]:
    """문자열/숫자 형태의 금액을 int로 변환. 실패하면 None."""
    if amount is None:
        return None
    s = str(amount).replace(",", "").strip()
    if s in ("", "-", "NaN"):
        return None
    try:
        return int(float(s))
    except Exception:
        return None


def _format_amount(amount: Optional[int]) -> str:
    """int 금액을 콤마 찍힌 문자열로 변환. None이면 '-'."""
    if amount is None:
        return "-"
    return f"{amount:,}"


# reprt_code → 사람이 읽기 좋은 이름
REPRT_CODE_LABELS: Dict[str, str] = {
    "11011": "사업보고서",
    "11012": "반기보고서",
    "11013": "1분기보고서",
    "11014": "3분기보고서",
}


# -----------------------------
# 1) 핵심 지표만 추출하는 함수
# -----------------------------
def extract_key_metrics(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Optional[int]]]:
    """
    DART 재무제표 rows(list[dict])에서
    자산총계, 부채총계, 자본총계, 매출액, 영업이익, 당기순이익(손실)
    의 '당기/전기/전전기' 금액을 뽑아서 표준화된 dict로 반환.

    반환 예시:
    {
        "assets":        {"th": 514531948000000, "fr": 455905980000000, "bf": 448424507000000},
        "liabilities":   {"th": ..., "fr": ..., "bf": ...},
        "equity":        {...},
        "revenue":       {...},
        "operating_income": {...},
        "net_income":    {...},
    }
    """
    # 기본 구조 (모두 None으로 초기화)
    summary: Dict[str, Dict[str, Optional[int]]] = {
        "assets": {"th": None, "fr": None, "bf": None},
        "liabilities": {"th": None, "fr": None, "bf": None},
        "equity": {"th": None, "fr": None, "bf": None},
        "revenue": {"th": None, "fr": None, "bf": None},
        "operating_income": {"th": None, "fr": None, "bf": None},
        "net_income": {"th": None, "fr": None, "bf": None},
    }

    for row in rows:
        account_nm = (row.get("account_nm") or "").replace(" ", "")
        th = _parse_int(row.get("thstrm_amount"))
        fr = _parse_int(row.get("frmtrm_amount"))
        bf = _parse_int(row.get("bfefrmtrm_amount"))

        # 재무상태표: 자산/부채/자본
        if "자산총계" in account_nm:
            # 이미 값이 있으면 덮어쓰지 않음 (첫 번째 값 유지)
            if summary["assets"]["th"] is None and th is not None:
                summary["assets"]["th"] = th
                summary["assets"]["fr"] = fr
                summary["assets"]["bf"] = bf

        elif "부채총계" in account_nm:
            if summary["liabilities"]["th"] is None and th is not None:
                summary["liabilities"]["th"] = th
                summary["liabilities"]["fr"] = fr
                summary["liabilities"]["bf"] = bf

        elif "자본총계" in account_nm:
            if summary["equity"]["th"] is None and th is not None:
                summary["equity"]["th"] = th
                summary["equity"]["fr"] = fr
                summary["equity"]["bf"] = bf

        # 손익계산서: 매출액 / 영업이익 / 당기순이익(손실)
        # 계정명 변형(예: 수익(매출액))을 조금 넉넉하게 처리
        elif "매출액" in account_nm or "수익(매출액)" in account_nm:
            if summary["revenue"]["th"] is None and th is not None:
                summary["revenue"]["th"] = th
                summary["revenue"]["fr"] = fr
                summary["revenue"]["bf"] = bf

        elif "영업이익" in account_nm:
            if summary["operating_income"]["th"] is None and th is not None:
                summary["operating_income"]["th"] = th
                summary["operating_income"]["fr"] = fr
                summary["operating_income"]["bf"] = bf

        elif "당기순이익" in account_nm:
            # 🔥 핵심: 첫 번째 non-None 값만 사용하고 이후 0/빈값으로 덮어쓰지 않음
            if summary["net_income"]["th"] is None and th is not None:
                summary["net_income"]["th"] = th
                summary["net_income"]["fr"] = fr
                summary["net_income"]["bf"] = bf

    return summary


# -----------------------------
# 2) ES / 벡터 DB에 넣기 좋은 문서 변환 함수
# -----------------------------
def build_finstat_document(
    corp_code: str,
    corp_name: str,
    bsns_year: str,
    reprt_code: str,
    metrics: Dict[str, Dict[str, Optional[int]]],
) -> Dict[str, Any]:
    """
    핵심 지표(metrics)를 이용해
    ElasticSearch / 벡터 DB에 넣기 좋은 하나의 "문서(dict)"로 변환.

    반환 예시:
    {
        "id": "00126380_2024_11011_finstat",
        "type": "finstat",
        "corp_code": "00126380",
        "corp_name": "삼성전자",
        "bsns_year": "2024",
        "reprt_code": "11011",
        "reprt_name": "사업보고서",
        "assets_th": 514531948000000,
        ...
        "text": "삼성전자 2024년 사업보고서 기준 재무제표 요약: 자산총계 514조..., ..."
    }

    - 숫자 필드는 ES에서 정량 필터/정렬할 때 사용
    - text 필드는 BM25 / 임베딩(벡터 DB)용으로 사용
    """
    reprt_name = REPRT_CODE_LABELS.get(reprt_code, reprt_code)

    # 편하게 꺼내기
    a = metrics.get("assets", {})
    l = metrics.get("liabilities", {})
    e = metrics.get("equity", {})
    r = metrics.get("revenue", {})
    o = metrics.get("operating_income", {})
    n = metrics.get("net_income", {})

    assets_th = a.get("th")
    liab_th = l.get("th")
    equity_th = e.get("th")
    rev_th = r.get("th")
    op_th = o.get("th")
    net_th = n.get("th")

    # 사람 읽기 좋은 요약 텍스트 (BM25 + 임베딩용)
    text_parts = [
        f"{corp_name} {bsns_year}년 {reprt_name} 기준 재무제표 요약입니다.",
        f"자산총계는 {_format_amount(assets_th)}원,",
        f"부채총계는 {_format_amount(liab_th)}원,",
        f"자본총계는 {_format_amount(equity_th)}원입니다.",
        f"매출액은 {_format_amount(rev_th)}원,",
        f"영업이익은 {_format_amount(op_th)}원,",
        f"당기순이익은 {_format_amount(net_th)}원 수준입니다.",
    ]
    text_summary = " ".join(text_parts)

    doc: Dict[str, Any] = {
        # 문서 ID (ES / 벡터DB에서 primary key처럼 사용 가능)
        "id": f"{corp_code}_{bsns_year}_{reprt_code}_finstat",
        "type": "finstat",

        # 기본 메타데이터
        "corp_code": corp_code,
        "corp_name": corp_name,
        "bsns_year": bsns_year,
        "reprt_code": reprt_code,
        "reprt_name": reprt_name,

        # 숫자 필드 (ES에서 range filter 등 가능)
        "assets_th": assets_th,
        "assets_fr": a.get("fr"),
        "assets_bf": a.get("bf"),
        "liabilities_th": liab_th,
        "liabilities_fr": l.get("fr"),
        "liabilities_bf": l.get("bf"),
        "equity_th": equity_th,
        "equity_fr": e.get("fr"),
        "equity_bf": e.get("bf"),
        "revenue_th": rev_th,
        "revenue_fr": r.get("fr"),
        "revenue_bf": r.get("bf"),
        "operating_income_th": op_th,
        "operating_income_fr": o.get("fr"),
        "operating_income_bf": o.get("bf"),
        "net_income_th": net_th,
        "net_income_fr": n.get("fr"),
        "net_income_bf": n.get("bf"),

        # 검색/임베딩용 텍스트
        "text": text_summary,
    }

    return doc
