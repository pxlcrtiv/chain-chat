"""chain-chat — ask on-chain history in plain English.

Streamlit chat UI over the bundled DuckDB/parquet snapshot.

Run (zero keys, fully offline):
    streamlit run app.py

With an LLM (any OpenAI-compatible endpoint):
    export OPENAI_API_KEY=sk-...
    export OPENAI_BASE_URL=https://api.openai.com/v1   # optional
    export CHAIN_CHAT_MODEL=gpt-4o-mini                # optional
    streamlit run app.py
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import streamlit as st

from chain_chat.answers import Answer
from chain_chat.canned import CANNED
from chain_chat.db import ChainDB
from chain_chat.nl2sql import ask, llm_from_env

REPO_ROOT = Path(__file__).resolve().parent
SNAPSHOT_DIR = REPO_ROOT / "data" / "snapshot"

st.set_page_config(
    page_title="chain-chat · ask on-chain history",
    page_icon="⛓️",
    layout="centered",
    initial_sidebar_state="expanded",
)


@st.cache_resource
def load_db() -> ChainDB:
    return ChainDB(SNAPSHOT_DIR)


@st.cache_resource
def load_llm():
    return llm_from_env()


@st.cache_data(show_spinner=False)
def snapshot_stats() -> dict:
    m = load_db().manifest
    return {
        "seed": m.get("seed"),
        "window": f"{m.get('start_date')} → {m.get('end_date')}",
        "transfers": f"{m.get('transfers', 0):,}",
        "labels": m.get("labels"),
        "tokens": m.get("tokens"),
    }


def render_answer(a) -> None:
    with st.chat_message("assistant"):
        st.markdown(a.text)
        if a.sql:
            with st.expander(f"SQL · read-only · {a.model or 'offline'}"):
                st.code(a.sql, language="sql")
            if a.columns and a.rows:
                df = pd.DataFrame(a.rows, columns=a.columns)
                st.dataframe(df, width="stretch", hide_index=True)
        if a.error == "offline-fallback":
            st.caption("Set `OPENAI_API_KEY` to unlock free-form questions.")


def answer_question(q: str) -> None:
    st.session_state.messages.append({"role": "user", "content": q})
    with st.chat_message("user"):
        st.markdown(q)
    llm = load_llm()
    try:
        a = ask(q, load_db(), llm=llm)
    except Exception as exc:  # noqa: BLE001 — surface unexpected failures in UI
        a = Answer(question=q, text=f"⚠️ Something went wrong: {exc}",
                   sql=None, model=None, error="crash")
    st.session_state.messages.append({"role": "assistant", "answer": a})
    render_answer(a)


def main() -> None:
    if not (SNAPSHOT_DIR / "manifest.json").exists():
        st.error(
            "Snapshot not found. Generate it first:\n\n"
            "`python scripts/fetch_parquet.py`\n\n"
            "then rerun `streamlit run app.py`.")
        return

    llm = load_llm()
    stats = snapshot_stats()

    with st.sidebar:
        st.markdown("### ⛓️ chain-chat")
        st.caption("Ask Ethereum history in plain English")
        st.divider()
        st.markdown("**Snapshot** (bundled, synthetic)")
        st.json(stats)
        engine = (f"🟢 LLM — {llm.display_name}" if llm
                  else "🟡 offline fallback (no key)")
        st.markdown(f"**Engine**: {engine}")
        st.divider()
        st.markdown("**Try one of these**")
        for ca in CANNED:
            if st.button(ca.canonical, key=f"canned-{ca.canonical[:12]}",
                         width="stretch"):
                st.session_state.pending = ca.canonical
        st.divider()
        st.caption("Synthetic testnet-style data — not financial advice. "
                   "No paid APIs.")

    st.title("Ask your chain history 💬")
    st.caption(
        "Schema-aware NL→SQL over a bundled DuckDB/parquet snapshot "
        "(USDC · UNI · WETH transfers + labeled addresses). "
        "[pxlcrtiv/chain-chat](https://github.com/pxlcrtiv/chain-chat)")

    if "messages" not in st.session_state:
        st.session_state.messages = []
    for msg in st.session_state.messages:
        if msg["role"] == "user":
            with st.chat_message("user"):
                st.markdown(msg["content"])
        else:
            render_answer(msg["answer"])

    if st.session_state.pop("pending", None):
        answer_question(st.session_state.pending)

    prompt = st.chat_input("Ask about on-chain history (e.g. which token "
                           "moved the most yesterday?)")
    if prompt:
        answer_question(prompt)


main()