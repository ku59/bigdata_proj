from typing import Any, Dict, List


def normalize_finstat_rows(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    DART 재무제표 rows에서 자산/부채/자본/매출/영업이익/당기순이익 등을 뽑아 표준화.
    실제로는 계정명, 계정코드 기준으로 매핑 테이블을 두고 처리하는 것이 좋음.
    """
    summary = {
        "assets": None,
        "liabilities": None,
        "equity": None,
        "revenue": None,
        "operating_income": None,
        "net_income": None,
    }

    for row in rows:
        account_nm = (row.get("account_nm") or "").replace(" ", "")
        thstrm_amount = row.get("thstrm_amount")

        if "자산총계" in account_nm:
            summary["assets"] = thstrm_amount
        elif "부채총계" in account_nm:
            summary["liabilities"] = thstrm_amount
        elif "자본총계" in account_nm:
            summary["equity"] = thstrm_amount
        elif "매출액" in account_nm:
            summary["revenue"] = thstrm_amount
        elif "영업이익" in account_nm:
            summary["operating_income"] = thstrm_amount
        elif "당기순이익" in account_nm:
            summary["net_income"] = thstrm_amount

    return summary

