**OpenDART Insight Agent (빅데이터 정보검색 팀프로젝트)**

네이버 뉴스 + DART 전자공시 데이터를 한 번에 검색해서  
기업의 최근 이슈와 재무 상태를 요약해 주는 생성형 검색 에이전트 프로젝트입니다.

**1. 이 프로젝트는 무엇을 하나요?**

이 프로젝트의 목표는 다음과 같습니다.

- 사용자가 **기업 이름이나 질문을 자연어로 입력**하면,
- 백엔드에서
  - DART 전자공시 API로 **공시 / 재무제표**를 가져오고
  - (추가 예정) 네이버 뉴스 API로 **최근 뉴스**를 가져온 뒤
  - ElasticSearch + 벡터DB를 이용해 **관련성이 높은 문장/문단을 검색**하고
- 마지막으로 LLM(생성형 AI)이  
  → **“공시 + 재무제표 + 뉴스”**를 바탕으로  
  → 기업의 현재 상황을 요약/설명해 주는 **검색 에이전트**입니다.

한마디로 **“DART + 뉴스 기반 기업 분석 요약 봇”** 을 만드는 프로젝트입니다.

## 2. 폴더 구조

dart-rag-agent/
├─ README.md
├─ .gitignore
├─ requirements.txt          # 또는 pyproject.toml
├─ .env.example              # 환경변수 예시 (키, URL 등)
│
├─ data/
│  ├─ raw/                   # 원본 데이터 (임시 저장용, git에 안 올림)
│  ├─ processed/             # 전처리된 텍스트, json 등
│  └─ samples/               # 데모용 샘플 데이터 (작은 사이즈만 git에 포함)
│
├─ configs/
│  ├─ elasticsearch.yaml     # ES 인덱스 설정, 매핑 등
│  ├─ vectordb.yaml          # 벡터 DB 설정
│  └─ agent_config.yaml      # 에이전트/워크플로우 파라미터
│
├─ src/
│  ├─ __init__.py
│  │
│  ├─ data_ingestion/        # (A 담당) DART/뉴스 수집 모듈
│  │  ├─ __init__.py
│  │  ├─ dart_client.py      # DART API 호출 (공시목록, 재무제표)
│  │  ├─ dart_parsers.py     # 공시/재무제표 파싱, 정제
│  │  ├─ news_client.py      # 네이버/구글 뉴스 API 호출
│  │  └─ build_corpus.py     # ES/벡터DB에 넣을 corpus 생성 스크립트
│  │
│  ├─ retrieval/             # (B 담당) ES + 벡터DB 검색 모듈
│  │  ├─ __init__.py
│  │  ├─ es_client.py        # ElasticSearch 연결, 인덱스 생성/검색
│  │  ├─ vectorstore.py      # 벡터DB(Chroma, ES dense 등) 래퍼
│  │  ├─ hybrid_retriever.py # BM25 + Embedding 결합 로직
│  │  └─ indexing.py         # 문서 색인 스크립트
│  │
│  ├─ agent/                 # (C 담당) LangChain / LangGraph 에이전트
│  │  ├─ __init__.py
│  │  ├─ tools.py            # DART, 뉴스, 검색 등을 Tool로 래핑
│  │  ├─ prompts.py          # 시스템/에이전트 프롬프트 정의
│  │  ├─ workflow_graph.py   # LangGraph 워크플로우 정의
│  │  └─ run_agent.py        # CLI에서 에이전트 테스트용 엔트리 포인트
│  │
│  ├─ app/                   # (D 담당) Streamlit / FastAPI 등 UI
│  │  ├─ __init__.py
│  │  ├─ main_app.py         # Streamlit 메인 앱
│  │  └─ components.py       # 차트, 표, 카드 UI 컴포넌트
│  │
│  └─ utils/
│     ├─ __init__.py
│     ├─ logging_utils.py    # 로그 설정
│     ├─ settings.py         # .env 읽어서 설정 관리
│     └─ formatting.py       # 금액 콤마, 조 단위 표시 등 포맷 함수
│
├─ notebooks/
│  ├─ 01_dart_api_test.ipynb          # DART API 실험용
│  ├─ 02_news_api_test.ipynb          # 뉴스 API 실험용
│  ├─ 03_embedding_vector_test.ipynb  # 임베딩/벡터 검색 실험
│  └─ 99_sandbox.ipynb                # 자유 실험
│
├─ tests/
│  ├─ test_dart_client.py
│  ├─ test_retriever.py
│  └─ test_agent_workflow.py
│
└─ docs/
   ├─ architecture.md         # 시스템 구조 설명
   ├─ api_design.md           # 내부 모듈/함수 설명
   └─ demo_scenarios.md       # 데모용 예시 질의/응답 시나리오
