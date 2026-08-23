"""LLM engine tests with a deterministic scripted mock — no network."""

import json

from chain_chat.nl2sql import LLMEngine, extract_json
from chain_chat.guardrails import GuardrailError


class ScriptedLLM:
    """Returns scripted responses; records every prompt it received."""

    def __init__(self, *responses: str):
        self.responses = list(responses)
        self.prompts: list[list[dict]] = []

    def chat(self, messages: list[dict]) -> str:
        self.prompts.append(messages)
        if not self.responses:
            raise AssertionError("unexpected extra LLM call")
        return self.responses.pop(0)

    @property
    def display_name(self):
        return "scripted-mock"


def j(sql: str) -> str:
    return json.dumps({"sql": sql})


def test_valid_llm_sql_is_executed(db):
    llm = ScriptedLLM(j("SELECT COUNT(*) AS n FROM transfers WHERE token = 'usdc'"),
                      "Found 412 USDC transfers.")
    engine = LLMEngine(db, llm, timeout=5)
    a = engine.answer("How many USDC transfers happened?")
    assert a.source == "llm"
    assert a.error is None
    assert a.text == "Found 412 USDC transfers."
    assert a.columns == ["n"]
    assert "LIMIT 500" in a.sql
    assert len(llm.prompts) == 2  # propose + summarize


def test_error_rewrite_loop_feeds_error_back(db):
    llm = ScriptedLLM(
        j("SELECT missing_column FROM transfers"),          # attempt 0: fails
        j("SELECT COUNT(*) AS n FROM transfers"),            # attempt 1: works
        "There are 900 transfers.",
    )
    engine = LLMEngine(db, llm, timeout=5)
    a = engine.answer("How many transfers are there?")
    assert a.source == "llm" and a.error is None
    _, _, direct, _ = db.query("SELECT count(*) FROM transfers")
    assert a.rows[0][0] == direct[0][0]  # real numbers from the snapshot
    # the corrected prompt must contain the previous error text
    feedback = llm.prompts[1][-1]["content"]
    assert "missing_column" in feedback


def test_guardrail_rejection_is_fed_back_and_blocked(db):
    llm = ScriptedLLM(
        j("DELETE FROM transfers"),                          # rejected
        j("SELECT COUNT(*) AS n FROM transfers"),            # corrected
        "Blocked, then counted.",
    )
    engine = LLMEngine(db, llm, timeout=5)
    a = engine.answer("Delete everything?")
    assert a.error is None
    feedback = llm.prompts[1][-1]["content"]
    assert "guardrail" in feedback
    # nothing was deleted
    _, _, rows, _ = db.query("SELECT count(*) FROM transfers")
    assert rows[0][0] > 0


def test_repeated_guardrail_failures_give_up_gracefully(db):
    llm = ScriptedLLM(j("DROP TABLE transfers"), j("DROP TABLE transfers"),
                      j("DROP TABLE transfers"))
    engine = LLMEngine(db, llm, timeout=5, max_rewrites=2)
    a = engine.answer("Drop the table")
    assert a.error is not None and "guardrail" in a.error
    assert "couldn't produce a valid query" in a.text


def test_parse_failure_retries(db):
    llm = ScriptedLLM("sorry, here is my json: {sql: SELECT 1}",  # bad JSON
                      j("SELECT COUNT(*) AS n FROM transfers"),
                      "Good.")
    engine = LLMEngine(db, llm, timeout=5)
    a = engine.answer("Count them")
    assert a.error is None and a.rows[0][0] > 0


def test_extract_json_handles_fenced_and_verbose_output():
    text = ('Sure! Here is the SQL:\n```json\n{"sql": "SELECT 1"}\n```\n'
            "Let me know if you need help.")
    assert extract_json(text) == {"sql": "SELECT 1"}
    assert extract_json('{"sql": "SELECT 2", "x": {"y": [1, 2]}}') == {
        "sql": "SELECT 2", "x": {"y": [1, 2]}}
    try:
        extract_json("no json here")
        raise AssertionError("should have raised")
    except ValueError:
        pass