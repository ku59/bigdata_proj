from typing import Any, Dict, List

import streamlit as st


def render_financial_cards(summary: Dict[str, Any]) -> None:
    cols = st.columns(3)
    cols[0].metric("자산", summary.get("assets"))
    cols[1].metric("부채", summary.get("liabilities"))
    cols[2].metric("자본", summary.get("equity"))

    cols2 = st.columns(3)
    cols2[0].metric("매출", summary.get("revenue"))
    cols2[1].metric("영업이익", summary.get("operating_income"))
    cols2[2].metric("당기순이익", summary.get("net_income"))


def render_news_list(news_items: List[Dict[str, Any]]) -> None:
    for item in news_items:
        st.markdown(f"- [{item.get('title')}]({item.get('link')})")


def render_agent_answer(answer: str) -> None:
    st.markdown("### AI 분석 리포트")
    st.write(answer)
