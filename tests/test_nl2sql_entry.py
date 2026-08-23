"""Entry-point tests — llm_from_env, ask() routing, answer payload shape."""

from chain_chat.nl2sql import ask, llm_from_env


def test_llm_from_env_none_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert llm_from_env() is None


def test_llm_from_env_with_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:9999/v1")
    monkeypatch.setenv("CHAIN_CHAT_MODEL", "tiny-model")
    llm = llm_from_env()
    assert llm is not None
    assert llm.model == "tiny-model"
    assert llm.base_url == "http://localhost:9999/v1"


def test_ask_rejects_empty_question(db):
    try:
        ask("   ", db)
        raise AssertionError("should have raised")
    except ValueError:
        pass


def test_answer_payload_shape(db):
    a = ask("Which token moved the most yesterday?", db)
    assert a.question
    assert isinstance(a.text, str) and len(a.text) > 10
    assert isinstance(a.sql, str)
    assert isinstance(a.columns, list)
    assert isinstance(a.rows, list)
    assert a.model and a.source in ("canned", "fallback", "llm")