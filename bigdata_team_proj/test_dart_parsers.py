# test_dart_parsers.py
"""
dart_parsers.py가 제대로 동작하는지 확인하는 테스트 스크립트.

1) DartClient.get_finstat() 으로 삼성전자 재무제표를 가져오고
2) extract_key_metrics() 로 핵심 지표(자산/부채/자본/매출/영업이익/당기순이익)를 뽑고
3) build_finstat_document() 로 ES/벡터DB에 넣기 좋은 문서 형태로 변환해서 출력
"""

from src.data_ingestion.dart_client import DartClient
from src.data_ingestion.dart_parsers import extract_key_metrics, build_finstat_document


# 삼성전자 corp_code (DART 기준 고유번호)
SAMSUNG_CORP_CODE = "00126380"


def test_dart_parsers():
    client = DartClient()

    # 1) 재무제표 원본 데이터 가져오기
    fs_data = client.get_finstat(
        corp_code=SAMSUNG_CORP_CODE,
        bsns_year="2024",     # 사업연도
        reprt_code="11011",   # 사업보고서
        # fs_div는 dart_client.py에서 기본값 "CFS"라고 가정
    )

    status = fs_data.get("status")
    message = fs_data.get("message")
    rows = fs_data.get("list", []) or []

    print("\n[재무제표 원본 호출 결과]")
    print(f"status = {status}, message = {message}")
    print(f"row 개수 = {len(rows)}")

    if status != "000" or not rows:
        print("  => 재무제표 데이터를 제대로 못 가져왔습니다. DART 응답을 확인해보세요.")
        return

    # 2) 핵심 지표 추출
    metrics = extract_key_metrics(rows)

    print("\n[핵심 지표 추출 결과]")
    for key, val in metrics.items():
        th = val.get("th")
        fr = val.get("fr")
        bf = val.get("bf")
        print(f"- {key}")
        print(f"    · 당기(th):   {th}")
        print(f"    · 전기(fr):   {fr}")
        print(f"    · 전전기(bf): {bf}")

    # 3) ES/벡터DB용 문서 생성
    doc = build_finstat_document(
        corp_code=SAMSUNG_CORP_CODE,
        corp_name="삼성전자",
        bsns_year="2024",
        reprt_code="11011",
        metrics=metrics,
    )

    print("\n[ES/벡터DB용 문서 예시]")
    print(f"- id:   {doc.get('id')}")
    print(f"- type: {doc.get('type')}")
    print(f"- corp: {doc.get('corp_name')} ({doc.get('corp_code')})")
    print(f"- year: {doc.get('bsns_year')}, reprt: {doc.get('reprt_name')}")
    print("\n[요약 텍스트]")
    print(doc.get("text"))

    print("\n[숫자 필드 체크]")
    print(f"  assets_th          = {doc.get('assets_th')}")
    print(f"  liabilities_th     = {doc.get('liabilities_th')}")
    print(f"  equity_th          = {doc.get('equity_th')}")
    print(f"  revenue_th         = {doc.get('revenue_th')}")
    print(f"  operating_income_th= {doc.get('operating_income_th')}")
    print(f"  net_income_th      = {doc.get('net_income_th')}")


if __name__ == "__main__":
    test_dart_parsers()
