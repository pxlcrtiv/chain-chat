"""chain-chat — golden queries.

The canonical question → SQL pairs the project ships and tests. They double as
few-shot examples in the LLM prompt, regression targets for the snapshot, and
documented sample queries in the README.
"""

from __future__ import annotations

from .db import ChainDB

GOLDEN = [
    {
        "id": "top_mover_yesterday",
        "question": "Which token moved the most yesterday?",
        "sql": (
            "WITH d AS (SELECT CAST(max(ts) AS DATE) - INTERVAL 1 DAY AS day "
            "FROM transfers) "
            "SELECT t.symbol AS token, "
            "ROUND(SUM(x.amount * t.usd_reference_price), 2) AS usd_volume, "
            "COUNT(*) AS transfers "
            "FROM transfers x JOIN tokens t ON t.token = x.token, d "
            "WHERE CAST(x.ts AS DATE) = d.day "
            "GROUP BY 1 ORDER BY 2 DESC LIMIT 3"
        ),
        "check": lambda rows: (
            len(rows) >= 1 and rows[0][0] in ("USDC", "UNI", "WETH")
            and float(rows[0][1]) > 0
        ),
        "note": "flagship demo — USD-normalized volume vs tokens.usd_reference_price",
    },
    {
        "id": "usdc_volume_30d",
        "question": "How much USDC was transferred in the last 30 days?",
        "sql": (
            "WITH win AS (SELECT max(ts) - INTERVAL 30 DAY AS lo FROM transfers) "
            "SELECT ROUND(SUM(amount), 2) AS usdc_amount, COUNT(*) AS transfers "
            "FROM transfers, win "
            "WHERE token = 'usdc' AND ts >= win.lo"
        ),
        "check": lambda rows: len(rows) == 1 and float(rows[0][0]) > 0
        and int(rows[0][1]) > 0,
        "note": "trailing-window aggregate",
    },
    {
        "id": "top_labeled_sender",
        "question": "Which labeled address sent the most transfers?",
        "sql": (
            "SELECT l.label, l.category, COUNT(*) AS sends "
            "FROM transfers x JOIN labels l ON l.address = x.from_address "
            "GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 1"
        ),
        "check": lambda rows: len(rows) == 1 and rows[0][0] != ""
        and int(rows[0][2]) > 0,
        "note": "label resolution via the address registry",
    },
    {
        "id": "per_token_7d",
        "question": "How many transfers per token in the last 7 days?",
        "sql": (
            "WITH win AS (SELECT max(ts) - INTERVAL 7 DAY AS lo FROM transfers) "
            "SELECT token, COUNT(*) AS n FROM transfers, win "
            "WHERE ts >= win.lo GROUP BY 1 ORDER BY 2 DESC"
        ),
        "check": lambda rows: len(rows) == 3 and sum(int(r[1]) for r in rows) > 0,
        "note": "group-by token over a short window",
    },
    {
        "id": "largest_weth_transfer",
        "question": "What was the largest single WETH transfer?",
        "sql": (
            "SELECT x.amount, l.label, x.to_address "
            "FROM transfers x LEFT JOIN labels l ON l.address = x.from_address "
            "WHERE x.token = 'weth' ORDER BY x.amount DESC LIMIT 1"
        ),
        "check": lambda rows: len(rows) == 1 and float(rows[0][0]) > 0,
        "note": "ORDER BY + LEFT JOIN label enrichment",
    },
    {
        "id": "daily_trend_7d",
        "question": "What was the transfer count per day for the last 7 days?",
        "sql": (
            "WITH win AS (SELECT max(ts) - INTERVAL 7 DAY AS lo FROM transfers) "
            "SELECT CAST(ts AS DATE) AS day, COUNT(*) AS n "
            "FROM transfers, win WHERE ts >= win.lo "
            "GROUP BY 1 ORDER BY 1"
        ),
        "check": lambda rows: len(rows) == 7,
        "note": "time-series shape (7 buckets, chronological)",
    },
    {
        "id": "top_exchange_receiver_30d",
        "question": "Which exchange received the most USD value in 30 days?",
        "sql": (
            "WITH win AS (SELECT max(ts) - INTERVAL 30 DAY AS lo FROM transfers) "
            "SELECT l.label, "
            "ROUND(SUM(x.amount * t.usd_reference_price), 2) AS usd_in "
            "FROM transfers x JOIN labels l ON l.address = x.to_address "
            "JOIN tokens t ON t.token = x.token, win "
            "WHERE x.ts >= win.lo AND l.category = 'exchange' "
            "GROUP BY 1 ORDER BY 2 DESC LIMIT 3"
        ),
        "check": lambda rows: len(rows) >= 1 and float(rows[0][1]) > 0,
        "note": "three-way join with category filter",
    },
]


def run_golden(db: ChainDB, timeout: float = 10.0) -> list[dict]:
    """Run every golden query; returns per-query results with pass/fail."""
    out = []
    for g in GOLDEN:
        try:
            _sql, columns, rows, truncated = db.query(g["sql"], timeout=timeout)
            ok = bool(g["check"](rows))
            out.append({"id": g["id"], "ok": ok, "columns": columns,
                        "rows": rows, "truncated": truncated, "error": None})
        except Exception as exc:  # noqa: BLE001
            out.append({"id": g["id"], "ok": False, "error": str(exc)})
    return out


def all_pass(results: list[dict]) -> bool:
    return all(r["ok"] for r in results)