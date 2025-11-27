from typing import Any, Dict, List, Optional
from fastapi import FastAPI, Body
from fastapi.responses import StreamingResponse, JSONResponse
import asyncio
import uvicorn
import time
from fastapi.middleware.cors import CORSMiddleware

# Reuse project tools/workflow
from src.agent.workflow_graph import build_workflow
from src.agent.prompts import SYSTEM_PROMPT
from src.agent.tools import (
    tool_get_finstat_bulk,
    tool_search_news,
    tool_hybrid_search,
)
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage
from src.utils.settings import settings

# Simple in-memory session store
SESSIONS: Dict[str, Dict[str, Any]] = {}

app = FastAPI(title="Agentic RAG Chat API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_session(session_id: str) -> Dict[str, Any]:
    if session_id not in SESSIONS:
        SESSIONS[session_id] = {
            "company_name": None,
            "corp_code": None,
            "stock_code": None,
            "years": [],
            "reprt_codes": [],
            "fs_div": "CFS",
            "history": [],  # [{"role": "user"/"assistant", "content": "..."}]
        }
    return SESSIONS[session_id]


def split_company_code(raw: Optional[str]) -> (Optional[str], Optional[str]):
    if not raw:
        return None, None
    s = raw.strip()
    if len(s) == 8:
        return s, None
    if len(s) == 6:
        return None, s
    return None, None


def intent_route(message: str) -> str:
    m = message.lower()
    # Very simple intent routing
    if ("재무" in m) or ("차트" in m):
        return "financial_chart"
    if "뉴스" in m:
        return "news"
    if ("보고서" in m) or ("브리핑" in m) or ("분석" in m):
        return "rag_report"
    return "rag_report"


@app.post("/chat")
def chat(
    session_id: str = Body(..., embed=True),
    user_message: str = Body(..., embed=True),
    company_name: Optional[str] = Body(None, embed=True),
    company_code: Optional[str] = Body(None, embed=True),  # corp_code(8) or stock_code(6)
    years: Optional[List[str]] = Body(None, embed=True),
    reprt_codes: Optional[List[str]] = Body(None, embed=True),
    fs_div: Optional[str] = Body(None, embed=True),  # "CFS"/"OFS"
) -> JSONResponse:
    """
    Synchronous chat endpoint returning structured payload by intent:
    - type: "chart" | "news" | "report"
    """
    sess = get_session(session_id)

    # Update session state if provided
    if company_name:
        sess["company_name"] = company_name
    if company_code:
        corp, stock = split_company_code(company_code)
        sess["corp_code"] = corp or sess.get("corp_code")
        sess["stock_code"] = stock or sess.get("stock_code")
    if years is not None:
        sess["years"] = years
    if reprt_codes is not None:
        sess["reprt_codes"] = reprt_codes
    if fs_div in ("CFS", "OFS"):
        sess["fs_div"] = fs_div

    # Append user message to history
    sess["history"].append({"role": "user", "content": user_message})

    route = intent_route(user_message)

    # Financial chart intent
    if route == "financial_chart":
        corp_code = sess.get("corp_code")
        years_list = sess.get("years") or []
        reprt_list = sess.get("reprt_codes") or ["11011"]
        fsd = sess.get("fs_div") or "CFS"
        if corp_code and years_list and reprt_list:
            items = tool_get_finstat_bulk(
                corp_code=corp_code,
                years=years_list,
                reprt_codes=reprt_list,
                fs_div=fsd,
            )
            # Return items so frontend can render chart/df
            payload = {
                "type": "chart",
                "data": items,
                "meta": {"years": years_list, "reprt_codes": reprt_list, "fs_div": fsd},
            }
        else:
            payload = {
                "type": "chart",
                "data": [],
                "meta": {"warning": "회사 코드/연도/보고서 선택이 부족합니다."},
            }
        sess["history"].append({"role": "assistant", "content": "[차트 데이터 전달]"})
        return JSONResponse(payload)

    # News intent
    if route == "news":
        comp = sess.get("company_name")
        if comp:
            news_items = tool_search_news(comp, limit=15, sort="date", dedup_strength="medium")
            payload = {"type": "news", "items": news_items}
        else:
            payload = {"type": "news", "items": [], "meta": {"warning": "회사명을 먼저 설정하세요."}}
        sess["history"].append({"role": "assistant", "content": "[뉴스 결과 전달]"})
        return JSONResponse(payload)

    # RAG report intent (default)
    corp_code = sess.get("corp_code")
    stock_code = sess.get("stock_code")
    # Try latest year from session years if present
    year = None
    if sess.get("years"):
        try:
            year = max(sess["years"], key=lambda y: int(y))
        except Exception:
            year = sess["years"][-1]

    # Retrieve hybrid context and use LLM to summarize (Agentic step)
    query = user_message
    if sess.get("company_name"):
        query = f"{sess['company_name']} {query}"
    docs = tool_hybrid_search(query=query, k=8, corp_code=corp_code, stock_code=stock_code, year=year)

    context_lines = []
    for d in docs[:8]:
        meta = d.get("metadata", {})
        src = meta.get("source", "unknown")
        yr = meta.get("year", "")
        context_lines.append(f"[{src} {yr}] {d['text']}")
    context = "\n".join(context_lines)

    # Use LangGraph workflow to generate the report (Agentic RAG)
    workflow = build_workflow()
    state = {
        "question": user_message,
        "company": sess.get("company_name"),
        "corp_code": sess.get("corp_code"),
        "stock_code": sess.get("stock_code"),
        "retrieved_docs": [],
        "answer": None,
        "route": None,
        "briefing_year": year,
        "briefing_year_mode": "selected" if year else "latest",
    }
    result = workflow.invoke(state)
    text = result.get("answer") or "결과가 없습니다."

    sess["history"].append({"role": "assistant", "content": text})
    return JSONResponse({"type": "report", "text": text, "refs": docs})


@app.post("/chat/stream")
async def chat_stream(
    session_id: str = Body(..., embed=True),
    user_message: str = Body(..., embed=True),
    company_name: Optional[str] = Body(None, embed=True),
    company_code: Optional[str] = Body(None, embed=True),
    years: Optional[List[str]] = Body(None, embed=True),
    reprt_codes: Optional[List[str]] = Body(None, embed=True),
    fs_div: Optional[str] = Body(None, embed=True),
) -> StreamingResponse:
    """
    Streaming endpoint (SSE-like) streaming LLM chunks.
    It builds quick context from hybrid search using session state.
    """

    sess = get_session(session_id)
    # Optional state update from stream request
    if company_name:
        sess["company_name"] = company_name
    if company_code:
        corp, stock = split_company_code(company_code)
        sess["corp_code"] = corp or sess.get("corp_code")
        sess["stock_code"] = stock or sess.get("stock_code")
    if years is not None:
        sess["years"] = years
    if reprt_codes is not None:
        sess["reprt_codes"] = reprt_codes
    if fs_div in ("CFS", "OFS"):
        sess["fs_div"] = fs_div

    corp_code = sess.get("corp_code")
    stock_code = sess.get("stock_code")
    year = None
    if sess.get("years"):
        try:
            year = max(sess["years"], key=lambda y: int(y))
        except Exception:
            year = sess["years"][-1]

    query = user_message
    if sess.get("company_name"):
        query = f"{sess['company_name']} {query}"
    docs = tool_hybrid_search(query=query, k=6, corp_code=corp_code, stock_code=stock_code, year=year)

    context_lines = []
    for d in docs[:6]:
        meta = d.get("metadata", {})
        src = meta.get("source", "unknown")
        yr = meta.get("year", "")
        context_lines.append(f"[{src} {yr}] {d['text']}")
    context = "\n".join(context_lines)

    llm = ChatGoogleGenerativeAI(model=settings.GEMINI_MODEL_NAME, temperature=0.2, google_api_key=settings.GOOGLE_API_KEY)

    async def gen():
        # Emit an initial status line
        yield f"data: 진행상황: 검색 근거 준비 완료\n\n"
        sys = SystemMessage(content=SYSTEM_PROMPT)
        usr = HumanMessage(content=f"질문: {user_message}\n회사: {sess.get('company_name') or '미지정'}\n근거:\n{context}\n요약 보고서를 한국어로 작성하세요.")
        try:
            # Stream chunks
            for chunk in llm.stream([sys, usr]):
                text = getattr(chunk, "text", None) or getattr(chunk, "content", "")
                if text:
                    yield f"data: {text}\n\n"
                await asyncio.sleep(0)  # allow event loop
            yield f"data: [END]\n\n"
        except Exception as e:
            yield f"data: 스트리밍 오류: {e}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


if __name__ == "__main__":
    uvicorn.run("src.api.chat_server:app", host="0.0.0.0", port=8000, reload=True)
