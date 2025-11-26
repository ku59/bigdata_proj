import streamlit as st

from src.agent.tools import tool_get_latest_finstat, tool_search_news
from src.agent.workflow_graph import build_workflow
from src.app.components import (
    render_agent_answer,
    render_financial_cards,
    render_news_list,
)
from src.utils.logging_utils import configure_logging


def main() -> None:
    configure_logging()
    st.set_page_config(page_title="DART RAG Agent", layout="wide")

    st.title("기업 분석 Agentic RAG 데모 (Gemini 기반)")

    company_name = st.text_input("회사명 (예: 삼성전자)")
    corp_code = st.text_input("DART 기업 코드 (예: 005930)")
    question = st.text_area("질문", "이 회사의 최근 실적과 리스크를 요약해줘")

    if st.button("분석 실행") and question:
        workflow = build_workflow()
        state = {
            "question": question,
            "company": company_name or None,
            "retrieved_docs": [],
            "answer": None,
            "route": None,
        }
        result = workflow.invoke(state)

        if corp_code:
            fin = tool_get_latest_finstat(corp_code=corp_code, year="2023")
            st.subheader("재무지표 요약")
            render_financial_cards(fin)

        if company_name:
            news = tool_search_news(company_name, limit=5)
            st.subheader("최근 뉴스")
            render_news_list(news)

        render_agent_answer(result["answer"])


if __name__ == "__main__":
    main()

