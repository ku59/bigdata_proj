# UI 고도화 및 데이터 조회/뉴스 중복 제거 작업 내역

## 개요
- 목적
  - Streamlit 기반 프론트엔드 UI를 “있어보이는” 형태로 개선
  - 프론트에서 DART 재무 데이터를 선택/전체 조회 가능하도록 확장
  - 네이버 뉴스 중복 문제 완화(클라이언트 레벨 간단한 중복 제거)
- 범위
  - UI: 사이드바 필터, 탭 레이아웃, 뉴스 카드, 재무 트렌드
  - 데이터: DART 멀티 연도/보고서 코드 조합 조회(bulk)
  - 뉴스: canonical URL/제목 정규화 기반 간단 중복 제거

## 변경 파일 목록
- `src/data_ingestion/news_client.py`
  - 간단하고 견고한 버전으로 재작성
  - `search(query, display, start, sort)` 기본 검색
  - `search_dedup(query, display, start, sort, dedup_strength)` 중복 제거 포함 검색
  - 내부 유틸
    - `_strip_html`, `_normalize_title`, `_canonical_url`, `_pick_latest`
- `src/agent/tools.py`
  - 기존 `tool_get_latest_finstat(corp_code, year)` 확장: 보고서 코드/연결/개별 선택 가능
  - 신규 `tool_get_finstat_bulk(corp_code, years, reprt_codes, fs_div)` 추가
  - `tool_search_news(corp_name, limit, sort, dedup_strength)` 파라미터 확장 및 dedup 활용
- `src/app/components.py`
  - `render_financial_cards(summary)` 개선(숫자 포맷)
  - `render_financial_trend(items)` 추가(연도별 평균 → 라인차트/테이블)
  - `render_news_cards(news_items, original_count)` 추가(카드형 UI)
- `src/app/main_app.py`
  - 사이드바 필터 추가(뉴스/공시 옵션)
  - 탭 레이아웃: 개요/뉴스/공시·재무/AI 브리핑
  - DART 단일/전체 조회 로직 연결
  - 뉴스 중복 제거 결과 카드 표시

## UI 상세
- 사이드바
  - 입력: 회사명, DART 기업 코드, 질문
  - 뉴스 옵션: 표시 수, 정렬(sim/date), 중복 제거 강도(low/medium/high)
  - 공시/재무 옵션: 연도 멀티 선택(2019–2025), 보고서 코드(11011/11012/11013/11014), 재무제표 기준(CFS/OFS)
  - “분석 실행” 버튼
- 탭
  - 개요: 입력 파라미터 요약 JSON
  - 뉴스: 카드형 결과(제목, 날짜, canonical URL, 요약)
  - 공시/재무
    - 단일 조회(연도 1개 + 보고서 코드 1개): 요약 카드
    - 전체 조회(멀티 조합): 트렌드 라인차트 + 표
  - AI 브리핑: 워크플로우 결과 표시

## DART 조회 플로우
- 단일 조회
  - `tool_get_latest_finstat(corp_code, year, reprt_code, fs_div)`
  - `DartClient.get_finstat` → `normalize_finstat_rows`로 핵심 지표 요약(th)
- 전체 조회(멀티)
  - `tool_get_finstat_bulk(corp_code, years, reprt_codes, fs_div)`
  - 선택된 연도 × 보고서 코드 조합으로 반복 호출
  - 결과를 DataFrame으로 변환하여 연도별 평균 집계 후 트렌드 시각화
- 주의
  - 현재는 `list_reports`를 사용한 정기공시(A001/A002/A003) 자동 수집은 포함하지 않음
  - 필요 시 사이드바에 정기공시 옵션을 추가하고 `list_reports` 연동 예정

## 뉴스 중복 제거(간단 버전)
- 원인
  - 네이버 뉴스 API는 동일 기사(타 언론 재송출, 제목 변형)를 다수 반환
- 방식
  - `canonical_url = _canonical_url(originallink or link)` 생성
  - canonical URL이 없으면 `title_norm = _normalize_title(title)`를 키로 사용
  - 키별 그룹에서 `pubDate` 최신 1건 선택
  - sort=`date`인 경우 `pubDate` 내림차순 정렬
  - UI 보강 필드 추가: `title_norm`, `description_clean`, `canonical_url`
- 장점
  - 표준 라이브러리만 사용해 간단/안정적
- 한계/향후 개선
  - 근사중복(제목 유사도) 클러스터링은 현재 생략(복잡성↓)
  - 향후 `difflib.SequenceMatcher` 또는 임베딩 기반 유사도 적용 가능

## 실행/테스트 방법
1. 의존성 확인
   - `requirements.txt` 기반 설치가 필요하면 진행
2. 실행
   - `streamlit run src/app/main_app.py`
3. 테스트 시나리오
   - 회사명: “삼성전자”
   - DART 코드: “005930”
   - 뉴스 표시 수/정렬/중복 제거 강도 조절
   - 연도: [2023] / 보고서 코드: [11011] → 단일 요약 카드
   - 연도: [2022, 2023, 2024] / 보고서 코드: [11011, 11012] → 트렌드 차트/표

## 기술적 작업 리스트 대응 현황
- 1. 데이터 수집 및 저장
  - 네이버 뉴스 수집 클라이언트 개선(중복 제거)
  - DART API 재무 조회 확장(단일/멀티)
- 2. Elasticsearch
  - 인덱스/매핑/하이브리드 검색은 설계 단계(향후 연동)
- 3. 임베딩 & RAG
  - UI·도구 수준에서 준비, 실제 임베딩/저장은 별도 작업 필요
- 4. Agentic RAG & LangGraph
  - 기존 워크플로우 유지, UI에서 결과 표시
- 5. Backend API
  - 현재 Streamlit 직호출로 동작, FastAPI 연동은 후속
- 6. 프론트엔드
  - 검색 입력 UI, 뉴스/공시 카드, 트렌드 차트, 브리핑 UI 구현
- 7. 테스트 및 데모
  - 대표 시나리오 실행 가이드 제공

## 다음 단계(권장)
- 정기공시(A001/A002/A003) 옵션 추가 및 `list_reports` 연동
- 뉴스 근사중복 제거(제목 유사도/임베딩) 단계적 도입
- ES 인덱싱 및 하이브리드 검색 연결
- FastAPI 백엔드 API(`/search/news`, `/search/dart`, `/rag/briefing`, `/agent/chat`) 구현
