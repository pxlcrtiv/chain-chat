"""chain-chat — canned answers (deterministic, zero-key fallback).

When no LLM key is configured, chain-chat still answers its three canonical
questions with real numbers, computed live from the snapshot. Everything else
gets a friendly pointer to the three questions or to setting OPENAI_API_KEY.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .answers import Answer, format_number, format_usd
from .db import ChainDB


@dataclass
class CannedAnswer:
    canonical: str
    sql: str
    explain: str
    render: Callable[[list], str] = field(default=lambda rows: "")
    patterns: list[tuple[str, ...]] = field(default_factory=list)

    def matches(self, question: str) -> int:
        q = question.lower()
        best = 0
        for pat in self.patterns:
            if all(tok in q for tok in pat):
                best = max(best, len(pat))
        return best


CANNED: list[CannedAnswer] = [
    CannedAnswer(
        canonical="Which token moved the most yesterday?",
        sql=(
            "WITH d AS (SELECT CAST(max(ts) AS DATE) - INTERVAL 1 DAY AS day "
            "FROM transfers) "
            "SELECT t.symbol AS token, "
            "ROUND(SUM(x.amount * t.usd_reference_price), 2) AS usd_volume, "
            "COUNT(*) AS transfers "
            "FROM transfers x JOIN tokens t ON t.token = x.token, d "
            "WHERE CAST(x.ts AS DATE) = d.day "
            "GROUP BY 1 ORDER BY 2 DESC LIMIT 3"
        ),
        explain=("Flagship question: top token by USD transfer volume on the "
                 "snapshot's 'yesterday' (max(ts) - 1 day), cross-token via "
                 "tokens.usd_reference_price."),
        render=lambda rows: (
            f"The most-moved token yesterday was **{rows[0][0]}** with ≈"
            f"{format_usd(rows[0][1])} of transfer volume across "
            f"{format_number(rows[0][2])} transfers"
            + (f"; next was {rows[1][0]} (≈{format_usd(rows[1][1])})"
               if len(rows) > 1 else "")
            + "."
        ),
        patterns=[
            ("which", "token", "moved", "most"),
            ("token", "moved", "most"),
            ("moved", "most", "yesterday"),
            ("top", "token", "yesterday"),
            ("biggest", "mover"),
            ("most", "active", "token"),
        ],
    ),
    CannedAnswer(
        canonical="How much USDC was transferred in the last 30 days?",
        sql=(
            "WITH win AS (SELECT max(ts) - INTERVAL 30 DAY AS lo FROM transfers) "
            "SELECT ROUND(SUM(amount), 2) AS usdc_amount, COUNT(*) AS transfers "
            "FROM transfers, win "
            "WHERE token = 'usdc' AND ts >= win.lo"
        ),
        explain=("Cumulative USDC transfer volume over the snapshot's trailing "
                 "30-day window."),
        render=lambda rows: (
            f"In the last 30 days, **{format_number(rows[0][0])} USDC** moved "
            f"across {format_number(rows[0][1])} transfers"
            + (f" (≈{format_usd(rows[0][0])} at the reference price)"
               if rows[0][0] else "")
            + "."
        ),
        patterns=[
            ("usdc", "last", "30", "days"),
            ("usdc", "30", "days"),
            ("how", "much", "usdc"),
            ("usdc", "volume", "month"),
            ("amount", "of", "usdc"),
        ],
    ),
    CannedAnswer(
        canonical="Which labeled address sent the most transfers?",
        sql=(
            "SELECT l.label, l.category, COUNT(*) AS sends "
            "FROM transfers x JOIN labels l ON l.address = x.from_address "
            "GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 1"
        ),
        explain=("Most active labeled sender by number of outgoing transfers, "
                 "labels resolved through the address registry."),
        render=lambda rows: (
            f"The most active labeled sender was **{rows[0][0]}** "
            f"({rows[0][1]}) with **{format_number(rows[0][2])}** outgoing "
            f"transfers in the snapshot."
        ),
        patterns=[
            ("labeled", "address", "sent", "most"),
            ("which", "address", "sent", "most"),
            ("top", "sender"),
            ("most", "active", "sender"),
            ("who", "sent", "most"),
        ],
    ),
]


def match_canned(question: str) -> CannedAnswer | None:
    best, best_score = None, 0
    for ca in CANNED:
        score = ca.matches(question)
        if score > best_score:
            best, best_score = ca, score
    return best if best_score > 0 else None


def _sanity(rows: list) -> bool:
    return bool(rows) and bool(rows[0]) and rows[0][0] is not None


class CannedEngine:
    """Deterministic fallback answering engine (zero keys)."""

    def __init__(self, db: ChainDB):
        self.db = db

    def answer(self, question: str, timeout: float = 10.0) -> Answer:
        ca = match_canned(question)
        if ca is None:
            return Answer(
                question=question,
                text=(
                    "I'm running in **offline mode** (no LLM key configured), "
                    "so I can only answer my three canned questions. Try one "
                    "of them — or set `OPENAI_API_KEY` (any OpenAI-compatible "
                    "endpoint) to ask anything else."
                ),
                sql=None, source="fallback",
                model="canned-answers (offline)", error="offline-fallback",
            )
        fixed, columns, rows, truncated = self.db.query(ca.sql, timeout=timeout)
        if not _sanity(rows):
            text = ("No data matched for that window in the bundled snapshot "
                    "— try a different question.")
        else:
            text = ca.render(rows)
        return Answer(question=question, text=text, sql=fixed,
                      columns=columns, rows=rows, truncated=truncated,
                      source="canned", model="canned-answers (offline)")