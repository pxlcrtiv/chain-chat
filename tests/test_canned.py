"""Canned fallback answer tests — deterministic, zero-key path."""

import pytest

from chain_chat.canned import CannedEngine, match_canned
from chain_chat.nl2sql import ask


@pytest.fixture(scope="module")
def canned(db):
    return CannedEngine(db)


def test_all_three_canned_questions_match():
    questions = [
        "Which token moved the most yesterday?",
        "How much USDC was transferred in the last 30 days?",
        "Which labeled address sent the most transfers?",
    ]
    for q in questions:
        assert match_canned(q) is not None, q


def test_canned_answers_compute_real_numbers(canned):
    a = canned.answer("How much USDC was transferred in the last 30 days?")
    assert a.source == "canned"
    assert a.error is None
    assert a.rows and a.rows[0][0] > 0
    assert "USDC" in a.text


def test_canned_top_mover(canned):
    a = canned.answer("Which token moved the most yesterday?")
    assert a.source == "canned"
    assert any(tok in a.text for tok in ("USDC", "UNI", "WETH"))
    assert a.sql and "LIMIT" in a.sql


def test_canned_numbers_match_direct_computation(canned):
    a = canned.answer("How much USDC was transferred in the last 30 days?")
    direct = canned.db.query(
        "WITH win AS (SELECT max(ts) - INTERVAL 30 DAY AS lo FROM transfers) "
        "SELECT ROUND(SUM(amount), 2) FROM transfers, win "
        "WHERE token = 'usdc' AND ts >= win.lo")[2][0][0]
    assert a.rows[0][0] == direct


def test_unknown_question_falls_back_gracefully(canned):
    a = canned.answer("What is the gas price on Arbitrum?")
    assert a.source == "fallback"
    assert a.error == "offline-fallback"
    assert "offline mode" in a.text.lower()


def test_ask_uses_canned_without_llm(db):
    a = ask("Which labeled address sent the most transfers?", db, llm=None)
    assert a.source == "canned"
    assert "sender" in a.text.lower()