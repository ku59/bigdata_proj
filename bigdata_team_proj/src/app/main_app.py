import os
import sys
import streamlit as st
import datetime as dt
import json

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
    
    # ✅ workflow에서 가져온 데이터 추출
    news_from_workflow = result.get("news_items", [])
    financial_from_workflow = result.get("financial")
    retrieved_docs = result.get("retrieved_docs", [])

    # ✅ 디버그 정보
    st.sidebar.markdown("### 🔍 디버그 정보")
    st.sidebar.write(f"Retrieved Docs: {len(retrieved_docs)}건")
    st.sidebar.write(f"News Items: {len(news_from_workflow)}건")
    st.sidebar.write(f"Financial Data: {'있음' if financial_from_workflow else '없음'}")
    st.sidebar.write(f"Answer: {'있음' if result.get('answer') else '없음'}")

    # ✅ RAG 소스 탭 추가
    tab_overview, tab_news, tab_fin, tab_briefing, tab_rag_source, tab_chat = st.tabs(
        ["개요", "뉴스", "공시/재무", "AI 브리핑", "RAG 소스", "대화"]
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
        
        # 디버그: workflow result 전체 구조 확인
        with st.expander("🐛 디버그: Workflow Result 전체 구조"):
            st.json({
                "keys": list(result.keys()),
                "retrieved_docs_count": len(result.get("retrieved_docs", [])),
                "news_items_count": len(result.get("news_items", [])),
                "has_financial": result.get("financial") is not None,
                "has_answer": result.get("answer") is not None,
                "route": result.get("route"),
            })

    with tab_fin:
        st.subheader("재무지표")
        if corp_code:
            # ✅ workflow 결과가 있으면 먼저 사용
            if financial_from_workflow and briefing_year:
                st.caption(f"브리핑 기준 연도: {briefing_year}")
                metrics_keys = ["assets", "liabilities", "equity", "revenue", "operating_income", "net_income"]
                if any(financial_from_workflow.get(k) is not None for k in metrics_keys):
                    render_financial_cards(financial_from_workflow)
                else:
                    st.warning("브리핑 연도 기준 재무 데이터가 없습니다.")
            else:
                # 기존 로직 유지 (사용자가 탭에서 직접 조회하는 경우)
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
            # ✅ workflow 결과 사용 (API 재호출 X)
            if news_from_workflow:
                render_news_cards(news_items=news_from_workflow, original_count=None)
            else:
                st.warning("뉴스 데이터를 가져올 수 없습니다.")
        else:
            st.info("회사명을 입력하면 뉴스가 표시됩니다.")

    with tab_briefing:
        st.subheader("AI 브리핑")
        if briefing_year:
            st.caption(f"브리핑 기준 연도: {briefing_year}")
        render_agent_answer(result.get("answer", "결과가 없습니다."))

    # ✅ RAG 소스 탭 - 3개 섹션으로 구성
    with tab_rag_source:
        st.subheader("AI 브리핑에 사용된 데이터 소스")
        st.caption("AI가 답변을 생성할 때 참고한 모든 데이터를 확인할 수 있습니다.")
        
        # ✅ 디버그 정보 추가
        with st.expander("🐛 디버그: 원본 데이터 구조 확인"):
            debug_info = {
                "result_keys": list(result.keys()),
                "retrieved_docs_type": str(type(retrieved_docs)),
                "retrieved_docs_length": len(retrieved_docs),
                "news_items_type": str(type(news_from_workflow)),
                "news_items_length": len(news_from_workflow),
                "financial_type": str(type(financial_from_workflow)),
                "financial_is_none": financial_from_workflow is None,
            }
            st.json(debug_info)
            
            if retrieved_docs:
                st.write("**첫 번째 retrieved_doc 샘플:**")
                st.json(retrieved_docs[0])
            
            if news_from_workflow:
                st.write("**첫 번째 news_item 샘플:**")
                st.json(news_from_workflow[0])
            
            if financial_from_workflow:
                st.write("**financial 데이터:**")
                st.json(financial_from_workflow)
        
        # 섹션 1: 하이브리드 검색 결과 (Vector + Keyword)
        st.markdown("### 📚 하이브리드 검색 문서 (ES + Vector DB)")
        st.caption(f"검색된 문서: 총 {len(retrieved_docs)}건")
        
        if retrieved_docs:
            for idx, doc in enumerate(retrieved_docs, 1):
                with st.expander(f"📄 문서 {idx} - {doc.get('metadata', {}).get('source', '출처 없음')}"):
                    # 메타데이터 정보
                    meta = doc.get("metadata", {})
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("출처", meta.get("source", "N/A"))
                    with col2:
                        st.metric("연도", meta.get("year", "N/A"))
                    with col3:
                        hybrid_score = doc.get("hybrid_score", 0)
                        st.metric("관련도 점수", f"{hybrid_score:.4f}")
                    
                    # 스코어 상세 정보
                    st.caption("**검색 스코어 상세**")
                    score_col1, score_col2, score_col3 = st.columns(3)
                    with score_col1:
                        st.write(f"🔍 하이브리드: `{doc.get('hybrid_score', 0):.4f}`")
                    with score_col2:
                        st.write(f"📊 키워드(Sparse): `{doc.get('sparse_score', 0):.4f}`")
                    with score_col3:
                        st.write(f"🧠 벡터(Dense): `{doc.get('dense_score', 0):.4f}`")
                    
                    # 문서 내용
                    st.markdown("**문서 내용:**")
                    st.text_area(
                        "내용",
                        value=doc.get("text", "내용 없음"),
                        height=150,
                        key=f"doc_{idx}",
                        label_visibility="collapsed"
                    )
        else:
            st.info("검색된 문서가 없습니다. Elasticsearch나 Vector DB에 데이터가 있는지 확인하세요.")
        
        st.divider()
        
        # 섹션 2: DART API 재무 데이터
        st.markdown("### 💼 DART API 재무 데이터")
        st.caption(f"브리핑 기준 연도: {briefing_year or 'N/A'}")
        
        if financial_from_workflow:
            with st.expander("📊 재무제표 요약 (DART Open API)", expanded=True):
                st.json(financial_from_workflow)
                
                # 주요 지표 시각화
                metrics_keys = ["assets", "liabilities", "equity", "revenue", "operating_income", "net_income"]
                has_data = any(financial_from_workflow.get(k) is not None for k in metrics_keys)
                
                if has_data:
                    st.markdown("**주요 재무 지표:**")
                    m_col1, m_col2, m_col3 = st.columns(3)
                    with m_col1:
                        if financial_from_workflow.get("assets"):
                            st.metric("총자산", f"{financial_from_workflow['assets']:,}백만원")
                        if financial_from_workflow.get("revenue"):
                            st.metric("매출액", f"{financial_from_workflow['revenue']:,}백만원")
                    with m_col2:
                        if financial_from_workflow.get("liabilities"):
                            st.metric("부채", f"{financial_from_workflow['liabilities']:,}백만원")
                        if financial_from_workflow.get("operating_income"):
                            st.metric("영업이익", f"{financial_from_workflow['operating_income']:,}백만원")
                    with m_col3:
                        if financial_from_workflow.get("equity"):
                            st.metric("자본", f"{financial_from_workflow['equity']:,}백만원")
                        if financial_from_workflow.get("net_income"):
                            st.metric("순이익", f"{financial_from_workflow['net_income']:,}백만원")
        else:
            st.info("DART 재무 데이터가 없습니다. 공시 고유코드와 브리핑 연도를 확인하세요.")
        
        st.divider()
        
        # 섹션 3: Naver News API 결과
        st.markdown("### 📰 Naver News API 결과")
        st.caption(f"검색된 뉴스: 총 {len(news_from_workflow)}건")
        
        if news_from_workflow:
            for idx, news_item in enumerate(news_from_workflow, 1):
                title = news_item.get("title") or news_item.get("titlenorm") or "제목 없음"
                pub_date = news_item.get("pubDate") or "날짜 없음"
                link = news_item.get("link") or news_item.get("originallink") or "#"
                desc = news_item.get("descriptionclean") or news_item.get("description") or "내용 없음"
                
                with st.expander(f"📰 뉴스 {idx} - {title}"):
                    st.markdown(f"**제목:** {title}")
                    st.markdown(f"**발행일:** {pub_date}")
                    st.markdown(f"**링크:** [{link}]({link})")
                    st.markdown(f"**요약:**")
                    st.write(desc)
                    
                    # 추가 메타데이터가 있으면 표시
                    if news_item.get("similarity_score"):
                        st.caption(f"유사도 점수: {news_item['similarity_score']:.4f}")
        else:
            st.info("네이버 뉴스 데이터가 없습니다. 회사명을 확인하세요.")

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
    st.caption("회사명, 공시 고유코드, 분석 질문을 입력하고 옵션을 선택한 뒤 '분석 실행'을 눌러주세요.")

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
        with st.spinner("분석 중... 잠시만 기다려주세요."):
            try:
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
                
                # ✅ 디버그: workflow 실행 결과 확인
                st.success(f"✅ 분석 완료! (Retrieved: {len(result.get('retrieved_docs', []))}건, News: {len(result.get('news_items', []))}건)")

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
                
            except Exception as e:
                st.error(f"❌ 분석 중 오류 발생: {str(e)}")
                st.exception(e)

    # 분석 상태가 있으면 항상 탭을 렌더링 (챗 입력 시에도 사라지지 않도록)
    analysis = st.session_state.get("analysis")
    if analysis:
        _render_tabs(analysis)
    else:
        st.info("분석을 실행하면 결과 탭이 표시됩니다.")


if __name__ == "__main__":
    main()
