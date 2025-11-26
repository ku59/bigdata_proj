from typing import Any, Dict, List, Literal, TypedDict

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from src.agent.prompts import SYSTEM_PROMPT
from src.agent.tools import tool_hybrid_search
from src.utils.settings import settings


class AgentState(TypedDict):
    question: str
    company: str | None
    retrieved_docs: List[Dict[str, Any]]
    answer: str | None
    route: Literal["general", "company"] | None


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

    docs = tool_hybrid_search(query=query, k=8)
    state["retrieved_docs"] = docs
    return state


def generate_answer(state: AgentState) -> AgentState:
    llm = ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL_NAME,
        temperature=0.2,
        google_api_key=settings.GOOGLE_API_KEY,  # 없으면 GOOGLE_API_KEY env 사용[web:47][web:50]
    )

    docs = state.get("retrieved_docs", [])
    company = state.get("company")

    context_lines = []
    for d in docs[:8]:
        meta = d.get("metadata", {})
        src = meta.get("source", "unknown")
        yr = meta.get("year", "")
        context_lines.append(f"[{src} {yr}] {d['text']}")

    context = "\n".join(context_lines)

    question = state["question"]
    system = SystemMessage(content=SYSTEM_PROMPT)
    user = HumanMessage(
        content=(
            f"질문: {question}\n"
            f"회사: {company or '미지정'}\n\n"
            f"다음은 검색으로 찾은 근거 문서입니다:\n{context}\n\n"
            "이 근거를 기반으로 투자 분석 보고서를 작성하세요."
        )
    )

    resp = llm.invoke([system, user])
    state["answer"] = getattr(resp, "text", None) or resp.content
    return state


def build_workflow():
    graph = StateGraph(AgentState)

    graph.add_node("route_intent", route_intent)
    graph.add_node("retrieve_evidence", retrieve_evidence)
    graph.add_node("generate_answer", generate_answer)

    graph.add_edge(START, "route_intent")
    graph.add_edge("route_intent", "retrieve_evidence")
    graph.add_edge("retrieve_evidence", "generate_answer")
    graph.add_edge("generate_answer", END)

    compiled = graph.compile()
    return compiled

