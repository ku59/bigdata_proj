from typing import Any, Dict, List, Optional

import streamlit as st
import pandas as pd


def _fmt_num(val: Optional[int]) -> str:
    if val is None:
        return "-"
    try:
        return f"{int(val):,}"
    except Exception:
        return str(val)


def render_financial_cards(summary: Dict[str, Any]) -> None:
    """
    단일 연도 재무 요약 카드를 표시.
    summary 예:
    {
        "assets": int|None,
        "liabilities": int|None,
        "equity": int|None,
        "revenue": int|None,
        "operating_income": int|None,
        "net_income": int|None,
    }
    """
    st.caption("핵심 재무 지표(당기 기준)")
    cols = st.columns(3)
    cols[0].metric("자산", _fmt_num(summary.get("assets")))
    cols[1].metric("부채", _fmt_num(summary.get("liabilities")))
    cols[2].metric("자본", _fmt_num(summary.get("equity")))

    cols2 = st.columns(3)
    cols2[0].metric("매출", _fmt_num(summary.get("revenue")))
    cols2[1].metric("영업이익", _fmt_num(summary.get("operating_income")))
    cols2[2].metric("당기순이익", _fmt_num(summary.get("net_income")))


def render_financial_trend(items: List[Dict[str, Any]]) -> None:
    """
    멀티 연도 × 보고서 코드 조합 결과를 트렌드 차트/테이블로 표시.
    데이터가 없거나 숫자 변환이 불가한 경우를 견고하게 처리.
    """
    if not items:
        st.warning("재무 데이터가 없습니다.")
        return

    st.subheader("연도별 재무 트렌드")
    df = pd.DataFrame(items)

    # 집계 대상 컬럼
    agg_cols = ["assets", "liabilities", "equity", "revenue", "operating_income", "net_income"]

    # 숫자 변환 시도 (None/문자열 → NaN)
    for c in agg_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    # 실제 존재하는 집계 대상만 선택
    present_cols = [c for c in agg_cols if c in df.columns]
    if not present_cols:
        st.warning("표시 가능한 재무 지표 컬럼이 없습니다.")
        st.dataframe(df, use_container_width=True)
        return

    # 연도별 평균 집계
    df_agg = df.groupby("year", as_index=False)[present_cols].mean()

    # 라인 차트 대상도 실제 존재하는 지표만
    chart_cols = [c for c in ["revenue", "operating_income", "net_income"] if c in df_agg.columns]
    if chart_cols:
        st.line_chart(df_agg.set_index("year")[chart_cols], height=260)
    else:
        st.info("차트로 표시할 수 있는 지표가 없습니다.")

    # 표 표시 (NaN 처리 포함)
    st.dataframe(
        df_agg.style.format({c: (lambda v: f"{int(v):,}" if pd.notna(v) else "-") for c in present_cols}),
        use_container_width=True,
    )


def render_news_cards(news_items: List[Dict[str, Any]], original_count: Optional[int] = None) -> None:
    """
    뉴스 결과를 카드 형태로 표시. 각 아이템 필드 예:
    {
      "title": "...",
      "link": "...",
      "originallink": "...",
      "pubDate": "...",
      "description": "...",
      "title_norm": "...",
      "canonical_url": "...",
      "description_clean": "..."
    }
    """
    if not news_items:
        st.info("표시할 뉴스가 없습니다.")
        return

    after_count = len(news_items)
    badge_text = f"총 {after_count}건"
    if original_count is not None and original_count > after_count:
        badge_text += f" (중복 제거 {original_count - after_count}건)"

    st.subheader("뉴스 결과")
    st.caption(badge_text)

    for item in news_items:
        with st.container():
            st.markdown(f"#### [{item.get('title')}]({item.get('link')})")
            meta_cols = st.columns(3)
            meta_cols[0].caption(item.get("pubDate", ""))
            meta_cols[1].caption((item.get("canonical_url") or item.get("originallink") or item.get("link") or "")[:80])
            src = item.get("originallink") or item.get("link")
            if src:
                meta_cols[2].button("원문 보기", key=f"news_btn_{src}", on_click=lambda url=src: st.write(url))
            desc = item.get("description_clean") or item.get("description") or ""
            if desc:
                st.write(desc)
            st.divider()


def render_agent_answer(answer: str) -> None:
    st.markdown("### AI 분석 리포트")
    st.write(answer)
