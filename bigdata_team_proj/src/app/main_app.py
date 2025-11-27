import os
import sys
import streamlit as st
import datetime as dt

# Ensure project root on sys.path for absolute imports like 'src.*'
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.agent.workflow_graph import build_workflow
from src.agent.tools import (
    tool_get_latest_finstat,
    tool_get_finstat_bulk,
    tool_search_news,
)
from src.app.components import (
    render_agent_answer,
    render_financial_cards,
    render_financial_trend,
    render_news_cards,
)
from src.utils.logging_utils import configure_logging
from src.agent.prompts import SYSTEM_PROMPT
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage
from src.utils.settings import settings


def _compute_briefing_year(mode_label: str, years: list[str], selected_brief_year: str | None) -> tuple[str, str | None]:
    if mode_label == "최신":
        briefing_year_mode = "latest"
        briefing_year = None
        if years:
            try:
                briefing_year = max(years, key=lambda y: int(y))
            except Exception:
                briefing_year = years[-1]
    else:
        briefing_year_mode = "selected"
        briefing_year = selected_brief_year
    return briefing_year_mode, briefing_year


def _split_company_code(raw: str | None) -> tuple[str | None, str | None]:
    """
    입력 문자열에서 공시 고유코드(8자리) 또는 주식 코드(6자리)를 구분하여 반환.
    - 반환: (corp_code, stock_code)
    """
    if not raw:
        return None, None
    s = raw.strip()
    if len(s) == 8:
        return s, None
    if len(s) == 6:
        return None, s
    return None, None


def _persist_analysis(params: dict, result: dict) -> None:
    st.session_state["analysis"] = {
        **params,
        "result": result,
    }


def _render_tabs(analysis: dict) -> None:
    company_name = analysis.get("company_name")
    corp_code = analysis.get("corp_code")
    question = analysis.get("question")
    years = analysis.get("years", [])
    reprt_codes = analysis.get("reprt_codes", [])
    fs_div = analysis.get("fs_div")
    news_sort = analysis.get("news_sort")
    news_limit = analysis.get("news_limit")
    dedup_strength = analysis.get("dedup_strength")
    sort_label = analysis.get("sort_label")
    dedup_label = analysis.get("dedup_label")
    briefing_year = analysis.get("briefing_year")
    briefing_year_mode = analysis.get("briefing_year_mode")
    result = analysis.get("result", {})

    tab_overview, tab_news, tab_fin, tab_briefing, tab_chat = st.tabs(
        ["개요", "뉴스", "공시/재무", "AI 브리핑", "대화"]
    )

    with tab_overview:
        st.subheader("개요")
        st.write("입력된 파라미터")
        st.json(
            {
                "회사명": company_name,
                "공시 고유코드": corp_code,
                "브리핑 기준": {"모드": briefing_year_mode, "연도": briefing_year},
                "뉴스": {"표시 수": news_limit, "정렬": sort_label, "중복 강도": dedup_label},
                "재무": {"연도": years, "보고서 코드": reprt_codes, "기준": fs_div},
            }
        )

    with tab_fin:
        st.subheader("재무지표")
        if corp_code:
            # 단일 조회 vs 전체(멀티) 조회
            if len(years) == 1 and len(reprt_codes) == 1:
                fin = tool_get_latest_finstat(
                    corp_code=corp_code,
                    year=years[0],
                    reprt_code=reprt_codes[0],
                    fs_div=fs_div,
                )
                metrics_keys = ["assets", "liabilities", "equity", "revenue", "operating_income", "net_income"]
                if any(fin.get(k) is not None for k in metrics_keys):
                    render_financial_cards(fin)
                else:
                    st.warning("해당 연도/보고서 조합으로 조회된 재무 데이터가 없습니다. 입력값을 확인하세요.")
            else:
                fin_items = tool_get_finstat_bulk(
                    corp_code=corp_code,
                    years=years,
                    reprt_codes=reprt_codes,
                    fs_div=fs_div,
                )
                if fin_items:
                    render_financial_trend(fin_items)
                else:
                    st.warning("선택한 조건에 해당하는 재무 데이터가 없습니다.")
        else:
            st.info("공시 고유코드를 입력하면 재무 지표가 표시됩니다. 예: 삼성전자 00126380")

    with tab_news:
        st.subheader("최근 뉴스")
        if company_name:
            news = tool_search_news(
                corp_name=company_name,
                limit=news_limit,
                sort=news_sort,
                dedup_strength=dedup_strength,
            )
            render_news_cards(news_items=news, original_count=None)
        else:
            st.info("회사명을 입력하면 뉴스가 표시됩니다.")

    with tab_briefing:
        st.subheader("AI 브리핑")
        if briefing_year:
            st.caption(f"브리핑 기준 연도: {briefing_year}")
        render_agent_answer(result.get("answer", "결과가 없습니다."))

    with tab_chat:
        st.subheader("대화")
        if "chat_history" not in st.session_state:
            st.session_state["chat_history"] = []

        for msg in st.session_state["chat_history"]:
            st.chat_message(msg["role"]).write(msg["content"])

        user_msg = st.chat_input("질문을 입력하세요")
        if user_msg:
            st.session_state["chat_history"].append({"role": "user", "content": user_msg})
            # 스트리밍 LLM 초기화
            llm = ChatGoogleGenerativeAI(
                model=settings.GEMINI_MODEL_NAME,
                temperature=0.2,
                google_api_key=settings.GOOGLE_API_KEY,
            )
            # 메시지 구성(간단한 컨텍스트 포함)
            sys = SystemMessage(content=SYSTEM_PROMPT)
            context = f"회사: {company_name or '미지정'} / 공시코드: {corp_code or '미지정'} / 기준연도: {briefing_year or '미지정'}"
            usr = HumanMessage(content=f"{context}\n질문: {user_msg}")

            assistant_box = st.chat_message("assistant")
            placeholder = assistant_box.empty()
            streamed = ""
            try:
                for chunk in llm.stream([sys, usr]):
                    text = getattr(chunk, "text", None) or getattr(chunk, "content", "")
                    if text:
                        streamed += text
                        placeholder.write(streamed)
                st.session_state["chat_history"].append({"role": "assistant", "content": streamed})
            except Exception:
                placeholder.write("스트리밍 중 오류가 발생했습니다.")


def main() -> None:
    configure_logging()
    st.set_page_config(page_title="DART RAG Agent", layout="wide")

    st.title("기업 분석 Agentic RAG 데모 (Gemini 기반)")
    st.caption("회사명, 공시 고유코드, 분석 질문을 입력하고 옵션을 선택한 뒤 ‘분석 실행’을 눌러주세요.")

    # 중앙 폼 UI (간소화 + 한 행에 옵션 배치)
    years_opts = [str(y) for y in range(2019, 2026)]
    reprt_code_map = {
        "사업보고서 (11011)": "11011",
        "반기보고서 (11012)": "11012",
        "1분기보고서 (11013)": "11013",
        "3분기보고서 (11014)": "11014",
    }

    with st.form("input_form"):
        st.subheader("기본 정보")
        col1, col2 = st.columns(2)
        with col1:
            company_name = st.text_input("회사명(예: 삼성전자)", placeholder="예: 삼성전자")
            corp_code = st.text_input("DART 공시 고유코드(예 : 00126380)", placeholder="예: 00126380")
        with col2:
            question = st.text_area("질문", value="이 회사의 최근 실적과 리스크를 요약해줘", height=120)

        st.divider()
        # 한 행에 뉴스 옵션과 공시/재무 옵션을 배치
        opt_left, opt_right = st.columns(2)

        with opt_left:
            st.subheader("뉴스 옵션")
            sort_label = st.radio("정렬", options=["유사도순", "날짜순"], index=0, horizontal=True)
            dedup_label = st.radio("중복 제거 강도", options=["약함", "보통", "강함"], index=1, horizontal=True)
            news_limit = st.slider("뉴스 표시 수", min_value=5, max_value=50, value=10, step=5)

        with opt_right:
            st.subheader("공시/재무 옵션")
            years_mode = st.radio("재무 연도 선택", options=["최근 1년", "최근 3년", "최근 5년", "수동 선택"], index=1, horizontal=True)
            if years_mode == "수동 선택":
                years = st.multiselect("연도 선택(복수 선택 가능)", options=years_opts, default=["2023"])
            else:
                current_year = dt.datetime.now().year
                if years_mode == "최근 1년":
                    chosen = [str(current_year)]
                elif years_mode == "최근 3년":
                    chosen = [str(y) for y in range(current_year - 2, current_year + 1)]
                else:  # 최근 5년
                    chosen = [str(y) for y in range(current_year - 4, current_year + 1)]
                years = [y for y in chosen if y in years_opts]
                st.caption(f"선택된 연도: {', '.join(years) if years else '없음'}")

            reprt_labels = st.multiselect(
                "보고서 종류",
                options=list(reprt_code_map.keys()),
                default=["사업보고서 (11011)"],
            )
            reprt_codes = [reprt_code_map[l] for l in reprt_labels]
            fs_div_label = st.radio("재무제표 기준", options=["연결(CFS)", "개별(OFS)"], index=0, horizontal=True)
            fs_div = "CFS" if fs_div_label.startswith("연결") else "OFS"

        st.divider()
        st.subheader("브리핑 기준")
        briefing_mode_label = st.radio("브리핑 기준 선택", options=["최신", "선택"], index=0, horizontal=True)
        selected_brief_year = None
        if briefing_mode_label == "선택":
            selected_brief_year = st.selectbox("브리핑 연도", options=years_opts, index=len(years_opts) - 3)

        submitted = st.form_submit_button("분석 실행")

    # 값 매핑
    news_sort = "sim" if sort_label == "유사도순" else "date"
    strength_map = {"약함": "low", "보통": "medium", "강함": "high"}
    dedup_strength = strength_map.get(dedup_label, "medium")

    # 브리핑 연도 결정
    briefing_year_mode, briefing_year = _compute_briefing_year(briefing_mode_label, years, selected_brief_year)

    # 폼 제출 시 분석 실행 및 상태 저장
    if submitted and question:
        workflow = build_workflow()
        code_corp, code_stock = _split_company_code(corp_code)
        state = {
            "question": question,
            "company": company_name or None,
            "corp_code": code_corp,
            "stock_code": code_stock,
            "retrieved_docs": [],
            "answer": None,
            "route": None,
            "briefing_year": briefing_year,
            "briefing_year_mode": briefing_year_mode,
        }
        result = workflow.invoke(state)

        params = {
            "company_name": company_name,
            "corp_code": corp_code,
            "question": question,
            "years": years,
            "reprt_codes": reprt_codes,
            "fs_div": fs_div,
            "news_sort": news_sort,
            "news_limit": news_limit,
            "dedup_strength": dedup_strength,
            "sort_label": sort_label,
            "dedup_label": dedup_label,
            "briefing_year": briefing_year,
            "briefing_year_mode": briefing_year_mode,
        }
        _persist_analysis(params, result)

    # 분석 상태가 있으면 항상 탭을 렌더링 (챗 입력 시에도 사라지지 않도록)
    analysis = st.session_state.get("analysis")
    if analysis:
        _render_tabs(analysis)
    else:
        st.info("분석을 실행하면 결과 탭이 표시됩니다.")


if __name__ == "__main__":
    main()
