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
    financial: Dict[str, Any] | None          # 단일 연도 재무 요약 (DART)
    news_items: List[Dict[str, Any]]          # 네이버 뉴스 아이템 리스트


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
                fs_div="CFS",        # 기본: 연결
            )
        except Exception:
            financial = None

    # 2) 뉴스 데이터 (회사명 기준)
    news_items: List[Dict[str, Any]] = []
    if company:
        try:
            news_items = tool_search_news(
                corp_name=company,
                limit=10,        # 최신 10건
                sort="date",     # 날짜순
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
        google_api_key=settings.GOOGLE_API_KEY,  # 없으면 GOOGLE_API_KEY env 사용
    )

    docs = state.get("retrieved_docs", [])
    company = state.get("company")
    byear = state.get("briefing_year")

    # 1) 하이브리드 검색 컨텍스트
    context_lines: List[str] = []
    for d in docs[:8]:
        meta = d.get("metadata", {})
        src = meta.get("source", "unknown")
        yr = meta.get("year", "")
        context_lines.append(f"[{src} {yr}] {d['text']}")
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
            "재무 요약(브리핑 연도 기준): "
            f"자산={assets}, 부채={liabilities}, 자본={equity}, "
            f"매출={revenue}, 영업이익={op_inc}, 순이익={net_inc}"
        )

    # 3) 뉴스 컨텍스트 (상위 3~5건만 요약)
    news_items = state.get("news_items", []) or []
    news_lines: List[str] = []
    for it in news_items[:5]:
        title = it.get("title") or it.get("titlenorm") or ""
        pub_date = it.get("pubDate") or ""
        desc = it.get("descriptionclean") or it.get("description") or ""
        news_lines.append(f"[{pub_date}] {title} - {desc}")
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
            "다음은 DART에서 조회한 재무 요약입니다:\n"
            f"{financial_context}\n\n"
        )

    if news_context:
        user_content += (
            "다음은 네이버 뉴스에서 조회한 최신 뉴스입니다:\n"
            f"{news_context}\n\n"
        )

    if context:
        user_content += (
            "다음은 검색으로 찾은 근거 문서입니다:\n"
            f"{context}\n\n"
        )

    user_content += "위 모든 근거를 종합해 투자 분석 보고서를 작성하세요."

    user = HumanMessage(content=user_content)

    resp = llm.invoke([system, user])
    state["answer"] = getattr(resp, "text", None) or resp.content
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

