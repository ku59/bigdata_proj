import os
import uuid
from typing import Any, Dict, List, Optional

import streamlit as st
import requests

# Ensure project root on sys.path for absolute imports like 'src.*'
import sys
import os as _os
PROJECT_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.app.components import render_financial_trend, render_news_cards

API_BASE = os.getenv("CHAT_API_URL", "http://localhost:8000")


def _ensure_session_id() -> str:
    if "chat_session_id" not in st.session_state:
        st.session_state["chat_session_id"] = str(uuid.uuid4())
    return st.session_state["chat_session_id"]


def _post_chat(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        resp = requests.post(f"{API_BASE}/chat", json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"type": "error", "error": str(e)}


def _stream_chat(session_id: str, user_message: str) -> None:
    try:
        with requests.post(
            f"{API_BASE}/chat/stream",
            json={"session_id": session_id, "user_message": user_message},
            stream=True,
            timeout=120,
        ) as resp:
            resp.raise_for_status()
            placeholder = st.empty()
            buf = ""
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                if isinstance(line, bytes):
                    line = line.decode("utf-8", errors="ignore")
                if line.startswith("data:"):
                    chunk = line[len("data:"):].strip()
                    if chunk == "[END]":
                        break
                    buf += chunk
                    placeholder.write(buf)
    except Exception as e:
        st.error(f"스트리밍 오류: {e}")


def main() -> None:
    st.set_page_config(page_title="대화형 분석(Chat)", layout="wide")
    st.title("대화형 Agentic RAG (CHAT API)")

    session_id = _ensure_session_id()

    # Quick settings row (한 행에 배치)
    st.subheader("대화 설정")
    col1, col2, col3 = st.columns([2, 2, 2])
    with col1:
        company_name = st.text_input("회사명", st.session_state.get("company_name_chat", ""))
        corp_or_stock_code = st.text_input("공시 고유코드(8자리) 또는 주식코드(6자리)", st.session_state.get("company_code_chat", ""))

    years_opts = [str(y) for y in range(2019, 2026)]
    reprt_code_map = {
        "사업보고서 (11011)": "11011",
        "반기보고서 (11012)": "11012",
        "1분기보고서 (11013)": "11013",
        "3분기보고서 (11014)": "11014",
    }

    with col2:
        years_mode = st.radio("재무 연도 선택", options=["최근 1년", "최근 3년", "최근 5년", "수동 선택"], index=1, horizontal=True)
        if years_mode == "수동 선택":
            years = st.multiselect("연도(복수 선택)", options=years_opts, default=st.session_state.get("years_chat", ["2023"]))
        else:
            import datetime as dt
            current_year = dt.datetime.now().year
            if years_mode == "최근 1년":
                chosen = [str(current_year)]
            elif years_mode == "최근 3년":
                chosen = [str(y) for y in range(current_year - 2, current_year + 1)]
            else:
                chosen = [str(y) for y in range(current_year - 4, current_year + 1)]
            years = [y for y in chosen if y in years_opts]
        st.caption(f"선택 연도: {', '.join(years) if years else '없음'}")

    with col3:
        reprt_labels = st.multiselect(
            "보고서 종류",
            options=list(reprt_code_map.keys()),
            default=st.session_state.get("reprt_labels_chat", ["사업보고서 (11011)"]),
        )
        reprt_codes = [reprt_code_map[l] for l in reprt_labels]
        fs_div_label = st.radio("재무제표 기준", options=["연결(CFS)", "개별(OFS)"], index=0, horizontal=True)
        fs_div = "CFS" if fs_div_label.startswith("연결") else "OFS"

    # Save settings to session
    if st.button("설정 저장"):
        st.session_state["company_name_chat"] = company_name
        st.session_state["company_code_chat"] = corp_or_stock_code
        st.session_state["years_chat"] = years
        st.session_state["reprt_labels_chat"] = reprt_labels
        st.success("설정을 저장했습니다.")

    st.divider()
    st.subheader("대화")
    if "chat_messages" not in st.session_state:
        st.session_state["chat_messages"] = []

    # Render existing messages
    for msg in st.session_state["chat_messages"]:
        st.chat_message(msg["role"]).write(msg["content"])

    # Input and controls
    use_stream = st.checkbox("스트리밍 응답 사용", value=True)
    user_msg = st.chat_input("메시지를 입력하세요")
    if user_msg:
        st.session_state["chat_messages"].append({"role": "user", "content": user_msg})

        # Build base payload (includes context settings)
        payload = {
            "session_id": session_id,
            "user_message": user_msg,
            "company_name": st.session_state.get("company_name_chat"),
            "company_code": st.session_state.get("company_code_chat"),
            "years": st.session_state.get("years_chat"),
            "reprt_codes": reprt_codes,
            "fs_div": fs_div,
        }

        # For intents like "재무 차트", first send settings in a light prompt
        if use_stream:
            assistant_box = st.chat_message("assistant")
            with assistant_box:
                _stream_chat(session_id=session_id, user_message=user_msg)
            # We also request a structured response for payloads (chart/news/report)
            result = _post_chat(payload)
        else:
            result = _post_chat(payload)

        # Handle structured payloads
        if result.get("type") == "chart":
            data = result.get("data") or []
            if data:
                render_financial_trend(data)
                st.session_state["chat_messages"].append({"role": "assistant", "content": "[재무 차트가 표시되었습니다.]"})
            else:
                st.warning("차트로 표시할 데이터가 없습니다.")
        elif result.get("type") == "news":
            items = result.get("items") or []
            if items:
                render_news_cards(items, original_count=None)
                st.session_state["chat_messages"].append({"role": "assistant", "content": "[뉴스 카드가 표시되었습니다.]"})
            else:
                st.warning("표시할 뉴스가 없습니다.")
        elif result.get("type") == "report":
            text = result.get("text") or ""
            st.chat_message("assistant").write(text)
            st.session_state["chat_messages"].append({"role": "assistant", "content": text})
        elif result.get("type") == "error":
            st.error(f"API 오류: {result.get('error')}")
        else:
            # Fallback: just show raw JSON
            st.chat_message("assistant").write(result)
            st.session_state["chat_messages"].append({"role": "assistant", "content": str(result)})


if __name__ == "__main__":
    main()
