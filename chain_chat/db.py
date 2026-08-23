"""chain-chat — DuckDB query layer.

Read-only, parameterized access to the bundled snapshot:
  * opens the compiled snapshot database (chainchat.db) in DuckDB
    read-only mode (engine-level write protection),
  * runs every statement through the SQL guardrails (SELECT/WITH only,
    no stacked statements, forced LIMIT),
  * executes under a wall-clock timeout with connection interrupt, so a
    runaway query cannot hang the app,
  * fetches at most max_rows + 1 rows (the +1 flags truncation).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import duckdb

from .guardrails import GuardrailError, validate

MAX_FETCH_ROWS = 500
DEFAULT_TIMEOUT_S = 10.0


class QueryError(Exception):
    """A database-level error (bad column, type mismatch...)."""


class QueryTimeoutError(Exception):
    """The query exceeded its time budget and was interrupted."""


class ChainDB:
    """Read-only query engine over a chain-chat snapshot directory."""

    def __init__(self, snapshot_dir: str | Path):
        self.dir = Path(snapshot_dir)
        self._lock = threading.Lock()
        self._conn: duckdb.DuckDBPyConnection | None = None
        self.manifest = self._load_manifest()

    # -- lifecycle ----------------------------------------------------------

    def _load_manifest(self) -> dict:
        p = self.dir / "manifest.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        return {}

    def _open(self) -> duckdb.DuckDBPyConnection:
        db_file = self.dir / "chainchat.db"
        if db_file.exists():
            return duckdb.connect(str(db_file), read_only=True)
        # Fallback: in-memory DB with views over the parquet files.
        conn = duckdb.connect()
        for table in ("transfers", "labels", "tokens"):
            path = self.dir / f"{table}.parquet"
            if path.exists():
                escaped = str(path).replace("'", "''")
                conn.execute(
                    f"CREATE VIEW {table} AS SELECT * FROM read_parquet('{escaped}')")
        return conn

    def _conn_locked(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            self._conn = self._open()
        return self._conn

    @property
    def tables(self) -> list[str]:
        return list((self.manifest.get("schema") or {}).keys()) or \
            ["transfers", "labels", "tokens"]

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None

    # -- query --------------------------------------------------------------

    def schema_sql(self) -> str:
        """CREATE TABLE–style schema dump used in the LLM prompt."""
        lines: list[str] = []
        casts = {
            "transfers": ("ts is a TIMESTAMP — use CAST(ts AS DATE) for dates; "
                          "amount is in token units (USDC has 6 decimals, "
                          "UNI/WETH 18, values are stored as floats)"),
            "labels": ("label is a human-readable name for an address; "
                       "category in (exchange, defi, treasury, bridge, "
                       "protocol, infra, known)"),
            "tokens": ("usd_reference_price is a static synthetic price in "
                       "USD — multiply transfer amounts by it to compare "
                       "volume across tokens"),
        }
        for table in self.tables:
            cols = self.manifest.get("schema", {}).get(table, [])
            lines.append(f"CREATE TABLE {table} (")
            for c in cols:
                lines.append(f"    {c},")
            lines.append(");")
            lines.append(f"-- note: {casts.get(table, '')}")
            lines.append("")
        return "\n".join(lines)

    def catalog(self, sample_rows: int = 3) -> str:
        """Human/LLM-readable catalog with row counts and sample values."""
        parts = [self.schema_sql()]
        with self._lock:
            conn = self._conn_locked()
            for table in self.tables:
                n = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                parts.append(f"{table}: {n:,} rows")
                cols = conn.execute(f"DESCRIBE {table}").fetchall()
                parts.append("  columns: " + ", ".join(
                    f"{c[0]} {c[1].upper()}" for c in cols))
                samples = conn.execute(
                    f"SELECT * FROM {table} LIMIT {sample_rows}").fetchall()
                parts.append("  sample rows:")
                for r in samples:
                    parts.append("    " + " | ".join(str(v) for v in r))
                parts.append("")
        return "\n".join(parts)

    def query(self, sql: str, params: list | dict | None = None,
              timeout: float = DEFAULT_TIMEOUT_S,
              max_rows: int = MAX_FETCH_ROWS) -> tuple[str, list[str], list, bool]:
        """Validate, run, and return (fixed_sql, columns, rows, truncated).

        params are always bound by DuckDB's parameter binding (never
        string-interpolated). Raises GuardrailError / QueryError /
        QueryTimeoutError.
        """
        fixed = validate(sql, max_rows=max_rows)
        outcome: dict = {}

        def run() -> None:
            try:
                with self._lock:
                    conn = self._conn_locked()
                    cur = conn.execute(fixed, params or [])
                    cols = [d[0] for d in cur.description] or []
                    rows = cur.fetchmany(max_rows + 1)
                outcome["columns"] = cols
                outcome["rows"] = rows
                # The guardrail-capped LIMIT makes an exact over-fetch
                # impossible; filling the cap is the truncation signal.
                outcome["truncated"] = len(rows) >= max_rows
                if outcome["truncated"]:
                    outcome["rows"] = rows[:max_rows]
            except Exception as exc:  # noqa: BLE001 — normalized below
                outcome["error"] = exc

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        worker.join(timeout)
        if worker.is_alive():
            # Abort the runaway query. The worker holds _lock while the query
            # runs, so we must NOT take the lock here — duckdb's interrupt()
            # is explicitly safe to call from another thread. Do not close the
            # connection either: close() waits for the in-flight query and
            # would deadlock. After interrupt the worker exits on its own and
            # the next query opens a fresh connection.
            conn = self._conn
            self._conn = None
            if conn is not None:
                try:
                    conn.interrupt()
                except Exception:
                    pass
            worker.join(5.0)
            raise QueryTimeoutError(
                f"query interrupted after {timeout:.1f}s (runaway query guard)")

        err = outcome.get("error")
        if err is not None:
            text = str(err)
            if "interrupt" in text.lower():
                raise QueryTimeoutError(f"query interrupted after {timeout:.1f}s")
            raise QueryError(text)
        return fixed, outcome["columns"], outcome["rows"], outcome["truncated"]