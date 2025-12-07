from typing import Any, Dict, List, Literal, TypedDict, Annotated, Sequence
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage, AIMessage
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from src.agent.prompts import SYSTEM_PROMPT
from src.agent.tools import (
    tool_hybrid_search,
    tool_get_latest_finstat,
    tool_search_news,
)
from src.utils.settings import settings


class AgentState(TypedDict):
    # 기존 상태
    question: str
    company: str | None
    corp_code: str | None
    stock_code: str | None
    retrieved_docs: List[Dict[str, Any]]
    answer: str | None
    route: Literal["general", "company"] | None
    briefing_year: str | None
    briefing_year_mode: Literal["latest", "selected"] | None
    financial: Dict[str, Any] | None
    news_items: List[Dict[str, Any]]
    data_sources: Dict[str, Any]
    
    # ReAct 패턴을 위한 메시지 히스토리
    messages: Annotated[Sequence[BaseMessage], add_messages]
    # 반복 제어
    iterations: int


# ========== LangChain Tool로 래핑 ==========

@tool
def search_documents(query: str, corp_code: str = None, stock_code: str = None, year: str = None, k: int = 8):
    """
    Elasticsearch에서 하이브리드 검색(BM25 + Dense Vector)으로 관련 문서를 검색합니다.
    Args:
        query: 검색 쿼리
        corp_code: 기업 코드 (선택)
        stock_code: 주식 코드 (선택)
        year: 연도 필터 (선택)
        k: 반환할 문서 수
    """
    docs = tool_hybrid_search(
        query=query,
        k=k,
        corp_code=corp_code,
        stock_code=stock_code,
        year=year,
    )
    return docs


@tool
def get_financial_data(corp_code: str, year: str, reprt_code: str = "11011", fs_div: str = "CFS"):
    """
    DART API에서 특정 기업의 재무제표 요약을 조회합니다.
    Args:
        corp_code: 기업 코드
        year: 조회 연도
        reprt_code: 보고서 코드 (기본: 11011 사업보고서)
        fs_div: 재무제표 구분 (기본: CFS 연결)
    """
    financial = tool_get_latest_finstat(
        corp_code=corp_code,
        year=year,
        reprt_code=reprt_code,
        fs_div=fs_div,
    )
    return financial


@tool
def search_company_news(corp_name: str, limit: int = 10, sort: str = "date", dedup_strength: str = "medium"):
    """
    네이버 뉴스 API에서 기업 관련 최신 뉴스를 검색합니다.
    Args:
        corp_name: 기업명
        limit: 조회할 뉴스 수
        sort: 정렬 기준 (date 또는 sim)
        dedup_strength: 중복 제거 강도
    """
    news_items = tool_search_news(
        corp_name=corp_name,
        limit=limit,
        sort=sort,
        dedup_strength=dedup_strength,
    )
    return news_items


# 도구 리스트
tools = [search_documents, get_financial_data, search_company_news]
tools_by_name = {tool.name: tool for tool in tools}


def route_intent(state: AgentState) -> AgentState:
    """질문 유형 분류"""
    q = state["question"]
    company = state.get("company")
    
    if company:
        route: Literal["general", "company"] = "company"
    elif any(k in q for k in ["실적", "영업이익", "재무", "매출", "PER", "PBR"]):
        route = "company"
    else:
        route = "general"
    
    state["route"] = route
    
    # 초기 메시지 설정
    if not state.get("messages"):
        initial_context = f"""
질문: {q}
회사: {company or '미지정'}
브리핑 연도: {state.get('briefing_year') or '미지정'}
corp_code: {state.get('corp_code') or '미지정'}
stock_code: {state.get('stock_code') or '미지정'}

이 질문에 답하기 위해 필요한 정보를 수집하세요.
"""
        state["messages"] = [HumanMessage(content=initial_context)]
    
    state["iterations"] = 0
    
    return state


def call_model(state: AgentState, config: RunnableConfig) -> AgentState:
    """
    ReAct의 Reasoning 단계: LLM이 현재 상태를 분석하고 다음 행동(도구 호출)을 결정
    """
    llm = ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL_NAME,
        temperature=0.2,
        google_api_key=settings.GOOGLE_API_KEY,
    )
    
    # 도구를 바인딩
    model_with_tools = llm.bind_tools(tools)
    
    # 시스템 프롬프트 추가
    system_msg = SystemMessage(content=f"""
{SYSTEM_PROMPT}

당신은 투자 분석 에이전트입니다. 다음 도구들을 사용할 수 있습니다:
1. search_documents: Elasticsearch에서 관련 문서 검색
2. get_financial_data: DART API에서 재무 데이터 조회
3. search_company_news: 네이버 뉴스에서 최신 뉴스 검색

질문에 답하기 위해 필요한 정보를 단계적으로 수집하세요.
- 먼저 문서 검색으로 배경 정보 수집
- 기업과 연도가 있으면 재무 데이터 조회
- 기업명이 있으면 최신 뉴스 검색
- 충분한 정보가 모이면 최종 답변 생성

현재 반복 횟수: {state.get('iterations', 0)}/5
""")
    
    # LLM 호출
    messages = [system_msg] + list(state["messages"])
    response = model_with_tools.invoke(messages, config)
    
    # 반복 횟수 증가
    state["iterations"] = state.get("iterations", 0) + 1
    
    return {"messages": [response]}


def call_tools(state: AgentState) -> AgentState:
    """
    ReAct의 Acting 단계: 선택된 도구를 실행하고 결과를 반환
    """
    last_message = state["messages"][-1]

    # 데이터 소스 추적 정보 초기화
    if not state.get("data_sources"):
        state["data_sources"] = {
            "es_docs_count": 0,
            "es_docs_detail": [],
            "dart_financial": None,
            "naver_news_count": 0,
            "naver_news_detail": [],
        }

    outputs: List[ToolMessage] = []

    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]

        try:
            # 도구별로 상태 정보 자동 주입
            if tool_name == "search_documents":
                if not tool_args.get("corp_code") and state.get("corp_code"):
                    tool_args["corp_code"] = state["corp_code"]
                if not tool_args.get("stock_code") and state.get("stock_code"):
                    tool_args["stock_code"] = state["stock_code"]
                if not tool_args.get("year") and state.get("briefing_year"):
                    tool_args["year"] = state["briefing_year"]

                result = tools_by_name[tool_name].invoke(tool_args)

                # 상태 업데이트
                state["retrieved_docs"] = result
                state["data_sources"]["es_docs_count"] = len(result)
                # 상위 8개 문서 메타 정보 저장
                state["data_sources"]["es_docs_detail"] = []  # 새로 채우기
                for i, doc in enumerate(result[:8], 1):
                    meta = doc.get("metadata", {})
                    state["data_sources"]["es_docs_detail"].append(
                        {
                            "index": i,
                            "source": meta.get("source", "unknown"),
                            "year": meta.get("year", ""),
                            "company": meta.get("company_name", ""),
                            "text_preview": doc.get("text", "")[:100],
                            "hybrid_score": doc.get("hybrid_score", 0),
                        }
                    )

            elif tool_name == "get_financial_data":
                if not tool_args.get("corp_code") and state.get("corp_code"):
                    tool_args["corp_code"] = state["corp_code"]
                if not tool_args.get("year") and state.get("briefing_year"):
                    tool_args["year"] = state["briefing_year"]

                result = tools_by_name[tool_name].invoke(tool_args)

                # 상태 업데이트
                state["financial"] = result
                if result:
                    state["data_sources"]["dart_financial"] = {
                        "year": tool_args.get("year"),
                        "assets": result.get("assets"),
                        "liabilities": result.get("liabilities"),
                        "equity": result.get("equity"),
                        "revenue": result.get("revenue"),
                        "operating_income": result.get("operating_income"),
                        "net_income": result.get("net_income"),
                    }

            elif tool_name == "search_company_news":
                if not tool_args.get("corp_name") and state.get("company"):
                    tool_args["corp_name"] = state["company"]

                result = tools_by_name[tool_name].invoke(tool_args)

                # 만약 tool_search_news가 dict를 반환한다면 여기서 items만 꺼내는 것도 고려
                # 예: items = result.get("items", result)
                # 지금은 result가 이미 뉴스 리스트라고 가정
                state["news_items"] = result
                state["data_sources"]["naver_news_count"] = len(result)

                state["data_sources"]["naver_news_detail"] = []  # 새로 채우기
                for i, item in enumerate(result[:5], 1):
                    state["data_sources"]["naver_news_detail"].append(
                        {
                            "index": i,
                            "title": item.get("title", ""),
                            "pub_date": item.get("pubDate", ""),
                            "description": item.get("description_clean", "")[:200],
                            "link": item.get("link", ""),
                        }
                    )

            else:
                # 등록되지 않은 기타 도구
                result = tools_by_name[tool_name].invoke(tool_args)

            # ToolMessage 생성
            outputs.append(
                ToolMessage(
                    content=str(result)[:500],  # 너무 길면 앞부분만
                    name=tool_name,
                    tool_call_id=tool_call["id"],
                )
            )

        except Exception as e:
            outputs.append(
                ToolMessage(
                    content=f"Error executing {tool_name}: {str(e)}",
                    name=tool_name,
                    tool_call_id=tool_call["id"],
                )
            )

    # 중요: 변경된 상태 필드를 모두 partial state로 반환해야 LangGraph가 merge해준다
    return {
        "messages": outputs,
        "retrieved_docs": state.get("retrieved_docs", []),
        "financial": state.get("financial"),
        "news_items": state.get("news_items", []),
        "data_sources": state["data_sources"],
    }



def should_continue(state: AgentState) -> Literal["continue", "generate_answer"]:
    """
    조건부 엣지: 도구 호출이 필요한지 또는 최종 답변을 생성할지 결정
    """
    messages = state["messages"]
    last_message = messages[-1]
    iterations = state.get("iterations", 0)
    
    # 최대 반복 횟수 체크
    if iterations >= 2:
        return "generate_answer"
    
    # 도구 호출이 있으면 계속
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "continue"
    
    # 도구 호출이 없으면 최종 답변 생성
    return "generate_answer"


def generate_answer(state: AgentState) -> AgentState:
    """
    모든 정보를 종합하여 최종 투자 분석 보고서 생성
    """
    llm = ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL_NAME,
        temperature=0.2,
        google_api_key=settings.GOOGLE_API_KEY,
    )
    
    # 수집된 모든 정보를 컨텍스트로 구성
    docs = state.get("retrieved_docs", [])
    financial = state.get("financial")
    news_items = state.get("news_items", [])
    
    context_parts = []
    
    # 1) 문서 검색 결과
    if docs:
        context_parts.append("=== Elasticsearch 검색 결과 ===")
        for i, d in enumerate(docs[:8], 1):
            meta = d.get("metadata", {})
            context_parts.append(
                f"[문서{i}: {meta.get('source', 'unknown')} {meta.get('year', '')} "
                f"{meta.get('company_name', '')}]\n{d['text'][:200]}..."
            )
    
    # 2) 재무 데이터
    if financial:
        context_parts.append("\n=== DART 재무 요약 ===")
        context_parts.append(
            f"연도: {state.get('briefing_year')}\n"
            f"자산: {financial.get('assets')}\n"
            f"부채: {financial.get('liabilities')}\n"
            f"자본: {financial.get('equity')}\n"
            f"매출: {financial.get('revenue')}\n"
            f"영업이익: {financial.get('operating_income')}\n"
            f"순이익: {financial.get('net_income')}"
        )
    
    # 3) 뉴스
    if news_items:
        context_parts.append("\n=== 네이버 최신 뉴스 ===")
        for i, item in enumerate(news_items[:5], 1):
            context_parts.append(
                f"[뉴스{i}] {item.get('title', '')} ({item.get('pubDate', '')})\n"
                f"{item.get('description_clean', '')[:100]}"
            )
    
    context = "\n\n".join(context_parts)
    
    # 최종 답변 생성 프롬프트
    final_prompt = f"""
{SYSTEM_PROMPT}

다음은 질문에 답하기 위해 수집한 모든 정보입니다:

{context}

원래 질문: {state['question']}
회사: {state.get('company', '미지정')}
브리핑 연도: {state.get('briefing_year', '미지정')}

위 모든 근거를 종합하여 투자 분석 보고서를 작성하세요.
각 정보의 출처(Elasticsearch, DART, 네이버 뉴스)를 명시하며 답변하세요.
"""
    
    response = llm.invoke([HumanMessage(content=final_prompt)])
    
    state["answer"] = getattr(response, "text", None) or response.content
    
    return state


def build_workflow():
    """ReAct 패턴 기반 워크플로우 구축"""
    graph = StateGraph(AgentState)
    
    # 노드 등록
    graph.add_node("route_intent", route_intent)
    graph.add_node("call_model", call_model)  # Reasoning 노드
    graph.add_node("call_tools", call_tools)  # Acting 노드
    graph.add_node("generate_answer", generate_answer)  # 최종 답변 생성
    
    # 실행 흐름 정의
    # START → route_intent → call_model
    graph.add_edge(START, "route_intent")
    graph.add_edge("route_intent", "call_model")
    
    # call_model 후 조건부 분기:
    # - tool_calls가 있으면 → call_tools → call_model (루프)
    # - tool_calls가 없으면 → generate_answer → END
    graph.add_conditional_edges(
        "call_model",
        should_continue,
        {
            "continue": "call_tools",
            "generate_answer": "generate_answer",
        }
    )
    
    # call_tools 후 다시 call_model로 (ReAct 루프)
    graph.add_edge("call_tools", "call_model")
    
    # generate_answer 후 종료
    graph.add_edge("generate_answer", END)
    
    compiled = graph.compile()
    return compiled

