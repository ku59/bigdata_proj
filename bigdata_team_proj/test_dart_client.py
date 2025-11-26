# test_dart_client.py
"""
1) 공시 목록(list_reports)
2) 재무제표(get_finstat) 를 잘 가져오는지 테스트하는 스크립트
"""

from src.data_ingestion.dart_client import DartClient


# 삼성전자 corp_code (DART 기준 고유번호)
SAMSUNG_CORP_CODE = "00126380"


def test_list_reports():
    client = DartClient()
    reports = client.list_reports(
        corp_code=SAMSUNG_CORP_CODE,
        bgn_de="20240101",   # 2024년 1월 1일부터
        end_de="",
        page_count=100,
        regular_only=True,   # 정기공시 + 사업/반기/분기만
    )

    print("\n[삼성전자 최근 공시 목록 테스트]")
    if not reports:
        print("  => 공시가 한 건도 안 나옴. 파라미터(bgn_de, end_de)를 확인 요망.")
        return

    for item in reports:
        corp_name = item.get("corp_name", "")
        report_nm = item.get("report_nm", "")
        rcept_no = item.get("rcept_no", "")
        rcept_dt = item.get("rcept_dt", "")
        print(f"- {corp_name} | {report_nm} | 접수번호: {rcept_no} | 접수일: {rcept_dt}")


def test_get_finstat():
    client = DartClient()
    fs_data = client.get_finstat(
        corp_code=SAMSUNG_CORP_CODE,
        bsns_year="2024",    # 사업연도 2024년
        reprt_code="11011",  # 기본: 사업보고서
    )

    status = fs_data.get("status")
    message = fs_data.get("message")
    fs_list = fs_data.get("list", [])

    print("\n[재무제표 호출 테스트]")
    print(f"status = {status}, message = {message}")
    print(f"재무제표 row 개수 = {len(fs_list)}")

    # 샘플로 앞 3줄만 계정명/금액 찍어보기
    for row in fs_list[:3]:
        sj_nm = row.get("sj_nm", "")
        account_nm = row.get("account_nm", "")
        th_amount = row.get("thstrm_amount", "")
        print(f"- [{sj_nm}] {account_nm} | 당기금액: {th_amount}")


if __name__ == "__main__":
    test_list_reports()
    test_get_finstat()

