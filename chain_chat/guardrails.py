"""chain-chat — SQL guardrails.

Safety layer between generated SQL and DuckDB:
  * only single read-only statements (SELECT / WITH ... SELECT) are allowed,
  * stacked statements ("SELECT 1; DROP TABLE ...") are rejected,
  * file/network access functions (read_parquet, read_csv, httpfs, ...) are
    rejected,
  * every statement gets an explicit LIMIT cap so a runaway query cannot
    materialize unlimited rows (enforced at the parser level AND by the
    connection layer in db.py).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Statements that mutate state or open files — rejected at the top level.
FORBIDDEN_STATEMENTS = {
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "ATTACH",
    "DETACH", "COPY", "EXPORT", "IMPORT", "PRAGMA", "GRANT", "REVOKE",
    "CALL", "VACUUM", "CHECKPOINT", "COMMENT", "PREPARE", "EXECUTE",
    "TRUNCATE", "REPLACE", "MERGE", "UPSERT", "LOAD", "INSTALL", "SECRET",
    "SET", "RESET", "BEGIN", "COMMIT", "ROLLBACK", "USE",
}

# Functions that touch files, network, or the process — rejected anywhere.
FORBIDDEN_FUNCTIONS = {
    "READ_PARQUET", "PARQUET_SCAN", "READ_CSV", "CSV_SCAN", "READ_JSON",
    "JSON_SCAN", "READ_BLOB", "READ_TEXT", "READ_FILE", "READ_NDJSON",
    "READ_JSON_AUTO", "GLOB", "ICEBERG_SCAN", "DELTA_SCAN", "HIVE_GLOB",
    "COPY", "WRITE_PARQUET", "EXPORT_DATABASE", "LOAD_EXTENSION",
    "INSTALL_EXTENSION", "CURRENT_SETTING", "GETENV", "FROM_ENV",
}

ALLOWED_FIRST = {"SELECT", "WITH"}


class GuardrailError(Exception):
    """Raised when SQL violates a guardrail (write statement, injection...)."""


@dataclass
class Scan:
    """Token-level scan of a single SQL statement."""

    top: list[str]      # keywords seen at parenthesis depth 0
    all: list[str]      # every keyword anywhere (for function denylist)
    bad_semicolon: bool  # a semicolon at depth 0, not just trailing


def _skip_quoted(sql: str, i: int) -> int:
    """Skip a '...' / \"...\" / `...` string or quoted identifier."""
    quote = sql[i]
    i += 1
    n = len(sql)
    while i < n:
        if sql[i] == quote:
            # doubled quote is an escaped quote for ' and "
            if i + 1 < n and sql[i + 1] == quote:
                i += 2
                continue
            return i + 1
        i += 1
    return i


def _skip_dollar_quote(sql: str, i: int) -> int:
    """Skip a $$...$$ (or $tag$...$tag$) string body."""
    n = len(sql)
    j = sql.find("$", i + 2)
    while j != -1:
        if sql[j:j + 2] == "$$":
            return j + 2
        j = sql.find("$", j + 1)
    return n


def scan(sql: str) -> Scan:
    """Tokenize one SQL statement; collect keywords, track paren depth."""
    top: list[str] = []
    all_toks: list[str] = []
    bad_semicolon = False
    i, n = 0, len(sql)
    depth = 0
    while i < n:
        c = sql[i]
        if c in "'\"`":
            i = _skip_quoted(sql, i)
            continue
        if c == "$" and i + 1 < n and sql[i + 1] == "$":
            i = _skip_dollar_quote(sql, i)
            continue
        if c == "-" and i + 1 < n and sql[i + 1] == "-":
            j = sql.find("\n", i)
            i = n if j == -1 else j + 1
            continue
        if c == "/" and i + 1 < n and sql[i + 1] == "*":
            j = sql.find("*/", i + 2)
            i = n if j == -1 else j + 2
            continue
        if c == ";":
            if depth == 0:
                bad_semicolon = True
            i += 1
            continue
        if c == "(":
            depth += 1
            i += 1
            continue
        if c == ")":
            depth = max(0, depth - 1)
            i += 1
            continue
        if c.isalpha() or c == "_":
            j = i
            while j < n and (sql[j].isalnum() or sql[j] in "_$"):
                j += 1
            kw = sql[i:j].upper()
            all_toks.append(kw)
            if depth == 0:
                top.append(kw)
            i = j
            continue
        i += 1
    return Scan(top=top, all=all_toks, bad_semicolon=bad_semicolon)


def validate(sql: str, max_rows: int = 500) -> str:
    """Validate a statement, reject writes/injections, enforce LIMIT.

    Returns a normalized statement guaranteed to end in LIMIT n (unless it
    already has a top-level LIMIT). Raises GuardrailError otherwise.
    """
    if not sql or not sql.strip():
        raise GuardrailError("empty SQL statement")
    s = sql.strip().rstrip(";").strip()
    sc = scan(s)

    if sc.bad_semicolon:
        raise GuardrailError("stacked statements are not allowed (found ';' inside the query)")

    if not sc.top:
        raise GuardrailError("no statement found")
    if sc.top[0] not in ALLOWED_FIRST:
        raise GuardrailError(
            f"only read-only SELECT/WITH queries are allowed (got '{sc.top[0]}')"
        )

    if FORBIDDEN_STATEMENTS & set(sc.top):
        bad = sorted(FORBIDDEN_STATEMENTS & set(sc.top))[0]
        raise GuardrailError(f"write/DDL statement '{bad}' is not allowed")

    if FORBIDDEN_FUNCTIONS & set(sc.all):
        bad = sorted(FORBIDDEN_FUNCTIONS & set(sc.all))[0]
        raise GuardrailError(f"function '{bad}' is not allowed (file/network access)")

    has_limit = "LIMIT" in sc.top
    fixed = s if has_limit else f"{s}\nLIMIT {int(max_rows)}"
    return fixed