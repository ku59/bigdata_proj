from typing import Any, Dict, List, Literal, TypedDict
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from src.agent.prompts import SYSTEM_PROMPT
from src.agent.tools import (
    tool_hybrid_search,
    tool_get_latest_finstat,
    tool_search_news,
)
from src.utils.settings import settings


class AgentState(TypedDict):
    question: str
    company: str | None
    corp_code: str | None
    stock_code: str | None
    retrieved_docs: List[Dict[str, Any]]
    answer: str | None
    route: Literal["general", "company"] | None
    briefing_year: str | None
    briefing_year_mode: Literal["latest", "selected"] | None
    # 재무/뉴스 API 결과를 에이전트 상태에 보관
    financial: Dict[str, Any] | None  # 단일 연도 재무 요약 (DART)
    news_items: List[Dict[str, Any]]  # 네이버 뉴스 아이템 리스트
    # 데이터 소스 추적 정보 추가
    data_sources: Dict[str, Any]  # 사용된 데이터 소스 상세 정보


def route_intent(state: AgentState) -> AgentState:
    q = state["question"]
    company = state.get("company")
    
    if company:
        route: Literal["general", "company"] = "company"
    elif any(k in q for k in ["실적", "영업이익", "재무", "매출", "PER", "PBR"]):
        route = "company"
    else:
        route = "general"
    
    state["route"] = route
    return state


def retrieve_evidence(state: AgentState) -> AgentState:
    query = state["question"]
    if state.get("company"):
        query = f"{state['company']} {query}"
    
    byear = state.get("briefing_year")
    if byear:
        # 연도를 쿼리에 반영하여 해당 연도의 근거 문서 검색을 강화
        query = f"{query} {byear}년"
    
    docs = tool_hybrid_search(
        query=query,
        k=8,
        corp_code=state.get("corp_code"),
        stock_code=state.get("stock_code"),
        year=state.get("briefing_year"),
    )
    
    state["retrieved_docs"] = docs
    return state


def fetch_realtime_data(state: AgentState) -> AgentState:
    """
    - corp_code + briefing_year가 있으면 해당 연도 DART 재무 요약을 조회
    - company가 있으면 네이버 뉴스에서 최신 뉴스(중복 제거)를 조회
    """
    corp_code = state.get("corp_code")
    company = state.get("company")
    byear = state.get("briefing_year")
    
    # 1) 재무 데이터 (브리핑 연도 기준 1개 요약)
    financial: Dict[str, Any] | None = None
    if corp_code and byear:
        try:
            financial = tool_get_latest_finstat(
                corp_code=corp_code,
                year=byear,
                reprt_code="11011",  # 기본: 사업보고서
                fs_div="CFS",  # 기본: 연결
            )
        except Exception:
            financial = None
    
    # 2) 뉴스 데이터 (회사명 기준)
    news_items: List[Dict[str, Any]] = []
    if company:
        try:
            news_items = tool_search_news(
                corp_name=company,
                limit=10,  # 최신 10건
                sort="date",  # 날짜순
                dedup_strength="medium",
            )
        except Exception:
            news_items = []
    
    state["financial"] = financial
    state["news_items"] = news_items
    return state


def generate_answer(state: AgentState) -> AgentState:
    llm = ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL_NAME,
        temperature=0.2,
        google_api_key=settings.GOOGLE_API_KEY,
    )
    
    docs = state.get("retrieved_docs", [])
    company = state.get("company")
    byear = state.get("briefing_year")
    
    # 데이터 소스 추적 정보 초기화
    data_sources = {
        "es_docs_count": 0,
        "es_docs_detail": [],
        "dart_financial": None,
        "naver_news_count": 0,
        "naver_news_detail": [],
    }
    
    # 1) 하이브리드 검색 컨텍스트
    context_lines: List[str] = []
    for i, d in enumerate(docs[:8], 1):
        meta = d.get("metadata", {})
        src = meta.get("source", "unknown")
        yr = meta.get("year", "")
        company_name = meta.get("company_name", "")
        
        context_lines.append(f"[문서{i}: {src} {yr} {company_name}] {d['text'][:200]}...")
        
        # ES 문서 상세 정보 저장
        data_sources["es_docs_detail"].append({
            "index": i,
            "source": src,
            "year": yr,
            "company": company_name,
            "text_preview": d['text'][:100],
            "hybrid_score": d.get("hybrid_score", 0),
            "sparse_score": d.get("sparse_score", 0),
            "dense_score": d.get("dense_score", 0),
        })
    
    data_sources["es_docs_count"] = len(context_lines)
    context = "\n".join(context_lines)
    
    # 2) 재무 요약 컨텍스트
    financial = state.get("financial")
    financial_context = ""
    if financial:
        assets = financial.get("assets")
        liabilities = financial.get("liabilities")
        equity = financial.get("equity")
        revenue = financial.get("revenue")
        op_inc = financial.get("operating_income")
        net_inc = financial.get("net_income")
        
        financial_context = (
            f"재무 요약(브리핑 연도 {byear}): "
            f"자산={assets}, 부채={liabilities}, 자본={equity}, "
            f"매출={revenue}, 영업이익={op_inc}, 순이익={net_inc}"
        )
        
        # DART 재무 정보 저장
        data_sources["dart_financial"] = {
            "year": byear,
            "assets": assets,
            "liabilities": liabilities,
            "equity": equity,
            "revenue": revenue,
            "operating_income": op_inc,
            "net_income": net_inc,
        }
    
    # 3) 뉴스 컨텍스트 (상위 3~5건만 요약)
    news_items = state.get("news_items", []) or []
    news_lines: List[str] = []
    for i, it in enumerate(news_items[:5], 1):
        title = it.get("title") or it.get("title_norm") or ""
        pub_date = it.get("pubDate") or ""
        desc = it.get("description_clean") or it.get("description") or ""
        
        news_lines.append(f"[뉴스{i}: {pub_date}] {title} - {desc[:100]}")
        
        # 뉴스 상세 정보 저장
        data_sources["naver_news_detail"].append({
            "index": i,
            "title": title,
            "pub_date": pub_date,
            "description": desc[:200],
            "link": it.get("link", ""),
        })
    
    data_sources["naver_news_count"] = len(news_lines)
    news_context = "\n".join(news_lines)
    
    # 4) 최종 프롬프트 생성
    question = state["question"]
    system = SystemMessage(content=SYSTEM_PROMPT)
    
    user_content = (
        f"질문: {question}\n"
        f"회사: {company or '미지정'}\n"
        f"브리핑 기준 연도: {byear or '미지정'}\n\n"
    )
    
    if financial_context:
        user_content += (
            "다음은 DART API에서 조회한 재무 요약입니다:\n"
            f"{financial_context}\n\n"
        )
    
    if news_context:
        user_content += (
            "다음은 네이버 뉴스 API에서 조회한 최신 뉴스입니다:\n"
            f"{news_context}\n\n"
        )
    
    if context:
        user_content += (
            "다음은 Elasticsearch에서 검색한 근거 문서입니다:\n"
            f"{context}\n\n"
        )
    
    user_content += "위 모든 근거를 종합해 투자 분석 보고서를 작성하세요."
    
    user = HumanMessage(content=user_content)
    resp = llm.invoke([system, user])
    
    state["answer"] = getattr(resp, "text", None) or resp.content
    state["data_sources"] = data_sources
    
    return state


def build_workflow():
    graph = StateGraph(AgentState)
    
    # 노드 등록
    graph.add_node("route_intent", route_intent)
    graph.add_node("retrieve_evidence", retrieve_evidence)
    graph.add_node("fetch_realtime_data", fetch_realtime_data)
    graph.add_node("generate_answer", generate_answer)
    
    # 실행 순서:
    # START → route_intent → retrieve_evidence → fetch_realtime_data → generate_answer → END
    graph.add_edge(START, "route_intent")
    graph.add_edge("route_intent", "retrieve_evidence")
    graph.add_edge("retrieve_evidence", "fetch_realtime_data")
    graph.add_edge("fetch_realtime_data", "generate_answer")
    graph.add_edge("generate_answer", END)
    
    compiled = graph.compile()
    return compiled

