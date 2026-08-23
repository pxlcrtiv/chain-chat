"""chain-chat — NL → SQL engine.

Pipeline for one question:
  1. schema-aware prompt (tables, columns, notes, few-shot examples),
  2. an OpenAI-compatible LLM proposes SQL (JSON),
  3. guardrails validate it (read-only, LIMIT, no injection),
  4. the query executes against the read-only snapshot,
  5. on any error the error text is fed back and the LLM rewrites (≤2 retries),
  6. a short summarization pass turns the result rows into the answer.

When no LLM is configured the engine falls back to the deterministic canned
answers (see canned.py) — the demo works with zero keys.
"""

from __future__ import annotations

import json
import os
from typing import Protocol

import requests

from .answers import Answer
from .canned import CannedEngine
from .db import ChainDB, QueryError, QueryTimeoutError
from .golden import GOLDEN
from .guardrails import GuardrailError


class ChatLM(Protocol):
    """Anything with a chat(messages) -> str interface (LLM or mock)."""

    @property
    def display_name(self) -> str: ...

    def chat(self, messages: list[dict]) -> str: ...

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"

SYSTEM_PROMPT = """You are chain-chat, an on-chain data analyst that answers \
natural-language questions by writing SQL over a bundled Ethereum transfer \
snapshot (DuckDB).

STRICT RULES
- Output ONLY JSON: {{"sql": "<one SELECT statement>"}} — nothing else.
- SELECT / WITH ... SELECT only. Single statement. No semicolons.
- Never touch files or network: no read_parquet, read_csv, glob, httpfs.
- Tables: transfers, labels, tokens (schema below).
- amounts are in token units; multiply by tokens.usd_reference_price to
  compare value across tokens (that price is a static synthetic reference).
- ts is a TIMESTAMP — use CAST(ts AS DATE) for day granularity.
- Always GROUP BY / ORDER BY sensibly; LIMIT results (default 10).

Schema:
{schema}

Examples (question -> SQL):
{examples}
"""

SUMMARY_PROMPT = """You are a concise on-chain data analyst. Summarize the \
query result below into 2-3 short sentences that directly answer the user's \
question. Use the exact numbers from the rows. If there are no rows, say no \
matching data was found.

Question: {question}

Columns: {columns}
Rows:
{rows}
"""


def extract_json(text: str) -> dict:
    """Pull the first balanced JSON object out of a model response."""
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object in model response")
    depth, in_str, i = 0, False, start
    while i < len(text):
        c = text[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
        i += 1
    raise ValueError("unbalanced JSON in model response")


def _render_rows(columns: list[str], rows: list, cap: int = 12) -> str:
    lines = []
    for r in rows[:cap]:
        lines.append(" | ".join(str(v) for v in r))
    if len(rows) > cap:
        lines.append(f"... ({len(rows) - cap} more rows)")
    return "\n".join(lines) if lines else "(no rows)"


class LLM:
    """Minimal OpenAI-compatible chat client (requests only, no SDK)."""

    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL,
                 model: str = DEFAULT_MODEL, timeout: float = 60.0):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    @property
    def display_name(self) -> str:
        return f"{self.model} via {self.base_url}"

    def chat(self, messages: list[dict], temperature: float = 0.0) -> str:
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"},
            json={"model": self.model, "messages": messages,
                  "temperature": temperature,
                  "max_tokens": 700},
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"LLM API error {resp.status_code}: "
                               f"{resp.text[:300]}")
        return resp.json()["choices"][0]["message"]["content"]


def llm_from_env() -> LLM | None:
    """Build a client from OPENAI_API_KEY etc., or None for offline mode."""
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return None
    return LLM(
        api_key=key,
        base_url=os.environ.get("OPENAI_BASE_URL", DEFAULT_BASE_URL),
        model=os.environ.get("CHAIN_CHAT_MODEL", DEFAULT_MODEL),
    )


class LLMEngine:
    """Key path: LLM-proposed SQL with execute-and-validate rewrite loop."""

    def __init__(self, db: ChainDB, llm: ChatLM, timeout: float = 15.0,
                 max_rewrites: int = 2):
        self.db = db
        self.llm = llm
        self.timeout = timeout
        self.max_rewrites = max_rewrites

    def system_prompt(self) -> str:
        examples = "\n".join(
            f"Q: {g['question']}\nSQL: {g['sql']}" for g in GOLDEN[:3])
        return SYSTEM_PROMPT.format(schema=self.db.schema_sql(),
                                    examples=examples)

    def _propose_sql(self, messages: list[dict]) -> str:
        raw = self.llm.chat(messages)
        return extract_json(raw)["sql"]

    def _summarize(self, question: str, columns: list[str],
                   rows: list) -> str:
        prompt = SUMMARY_PROMPT.format(
            question=question, columns=", ".join(columns),
            rows=_render_rows(columns, rows))
        try:
            return self.llm.chat([
                {"role": "system",
                 "content": "You are a concise on-chain data analyst."},
                {"role": "user", "content": prompt},
            ]).strip()
        except Exception as exc:  # noqa: BLE001 — fall back to raw rows
            return (f"I couldn't summarize the results ({exc}); here are the "
                    f"raw rows:\n{_render_rows(columns, rows)}")

    def answer(self, question: str) -> Answer:
        messages = [
            {"role": "system", "content": self.system_prompt()},
            {"role": "user", "content": question},
        ]
        last_err = None
        for attempt in range(self.max_rewrites + 1):
            try:
                sql = self._propose_sql(messages)
                fixed, columns, rows, truncated = self.db.query(
                    sql, timeout=self.timeout)
                text = self._summarize(question, columns, rows)
                return Answer(question=question, text=text, sql=fixed,
                              columns=columns, rows=rows, truncated=truncated,
                              source="llm", model=self.llm.display_name)
            except GuardrailError as exc:
                last_err = f"guardrail: {exc}"
            except (QueryError, QueryTimeoutError) as exc:
                last_err = f"query: {exc}"
            except (ValueError, KeyError, TypeError) as exc:
                last_err = f"parse: {exc}"
            messages.append({"role": "assistant",
                             "content": f"(attempt {attempt + 1} failed)"})
            messages.append({"role": "user",
                             "content": f"Your previous SQL was rejected "
                                        f"({last_err}). Return corrected JSON "
                                        f"with a working SELECT statement."})
        return Answer(question=question, text=(
            f"I couldn't produce a valid query after "
            f"{self.max_rewrites + 1} attempts ({last_err}). Try rephrasing "
            "the question."), sql=None, columns=[], rows=[],
            source="llm", model=self.llm.display_name, error=last_err)


def ask(question: str, db: ChainDB, llm: ChatLM | None = None,
        timeout: float = 15.0) -> Answer:
    """Answer a question: LLM path when available, canned fallback otherwise."""
    q = question.strip()
    if not q:
        raise ValueError("empty question")
    if llm is not None:
        return LLMEngine(db, llm, timeout=timeout).answer(q)
    return CannedEngine(db).answer(q, timeout=timeout)