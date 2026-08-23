"""Query layer tests — read-only enforcement, parameters, timeout."""

import duckdb
import pytest

from chain_chat.db import ChainDB, QueryError, QueryTimeoutError
from chain_chat.guardrails import GuardrailError


def test_query_returns_rows_and_columns(db):
    sql, columns, rows, truncated = db.query(
        "SELECT token, COUNT(*) AS n FROM transfers GROUP BY 1 ORDER BY 2 DESC")
    assert columns == ["token", "n"]
    assert len(rows) == 3
    assert {r[0] for r in rows} == {"usdc", "uni", "weth"}
    assert truncated is False


def test_snapshot_has_expected_volume(db):
    sql, _, rows, _ = db.query("SELECT count(*) FROM transfers")
    n = rows[0][0]
    assert n > 1000  # 30 days x 60/day, gaussian noise


def test_write_via_engine_rejected(db):
    with pytest.raises(GuardrailError):
        db.query("DELETE FROM transfers")


def test_compiled_db_is_read_only(snapshot_dir):
    """The on-disk DB sits behind duckdb read_only=True — engine-level block."""
    con = duckdb.connect(str(snapshot_dir / "chainchat.db"), read_only=True)
    try:
        with pytest.raises(duckdb.Error):
            con.execute("CREATE TABLE evil (x INT)")
        with pytest.raises(duckdb.Error):
            con.execute("INSERT INTO transfers VALUES (1)")
    finally:
        con.close()


def test_parameter_binding_never_interpolated(db):
    # A hostile value is bound, not spliced into SQL — must return 0 rows.
    sql, _, rows, _ = db.query(
        "SELECT count(*) FROM transfers WHERE token = ?",
        params=["usdc' OR '1'='1"])
    assert rows[0][0] == 0


def test_named_parameters_and_like(db):
    sql, _, rows, _ = db.query(
        "SELECT count(*) FROM transfers WHERE token = $t AND tx_hash LIKE $h",
        params={"t": "usdc", "h": "0x0000000000000000000000000000000000000000%"})
    assert rows[0][0] > 0


def test_truncation_flag_and_cap(db):
    sql, columns, rows, truncated = db.query(
        "SELECT tx_hash FROM transfers", max_rows=5)
    assert len(rows) == 5
    assert truncated is True
    assert sql.rstrip().endswith("LIMIT 5")


def test_runaway_query_is_interrupted(db):
    with pytest.raises(QueryTimeoutError):
        db.query(
            "WITH RECURSIVE x AS (SELECT 1 AS n UNION ALL "
            "SELECT n + 1 FROM x WHERE n < 1000000000) "
            "SELECT count(*) FROM x",
            timeout=0.1)
    # connection must be usable again after the interrupt
    _, _, rows, _ = db.query("SELECT count(*) FROM transfers")
    assert rows[0][0] > 0


def test_bad_column_raises_query_error(db):
    with pytest.raises(QueryError):
        db.query("SELECT definitely_not_a_column FROM transfers")


def test_schema_and_catalog_for_prompt(db):
    schema = db.schema_sql()
    for table in ("transfers", "labels", "tokens"):
        assert f"CREATE TABLE {table} (" in schema
    catalog = db.catalog(sample_rows=1)
    assert "transfers:" in catalog and "sample rows:" in catalog