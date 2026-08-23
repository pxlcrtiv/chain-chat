"""SQL guardrail tests — injection, writes, stacked statements, LIMIT."""

import pytest

from chain_chat.guardrails import GuardrailError, validate

WRITE_ATTEMPTS = [
    "INSERT INTO transfers VALUES (1)",
    "UPDATE transfers SET amount = 0",
    "DELETE FROM transfers",
    "DROP TABLE transfers",
    "ALTER TABLE transfers ADD COLUMN x INT",
    "CREATE TABLE evil (x INT)",
    "ATTACH 'foo.db' AS f",
    "PRAGMA writable_schema",
    "COPY transfers TO '/tmp/x.parquet'",
    "GRANT ALL ON transfers TO me",
    "CALL some_proc()",
    "LOAD 'lib.so'",
    "INSTALL 'httpfs'",
    "SET memory_limit = '1GB'",
    "BEGIN; SELECT 1; COMMIT",
]


@pytest.mark.parametrize("sql", WRITE_ATTEMPTS)
def test_rejects_write_statements(sql):
    with pytest.raises(GuardrailError):
        validate(sql)


@pytest.mark.parametrize("sql", [
    "SELECT 1; DROP TABLE transfers;",
    "SELECT 1; SELECT 2",
    "SELECT * FROM transfers; DELETE FROM transfers",
    "WITH x AS (SELECT 1) SELECT * FROM x; INSERT INTO transfers VALUES (1)",
])
def test_rejects_stacked_statements(sql):
    with pytest.raises(GuardrailError):
        validate(sql)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM read_parquet('/etc/passwd')",
    "SELECT * FROM parquet_scan('x.parquet')",
    "SELECT * FROM glob('/tmp/*')",
    "SELECT * FROM read_csv('x.csv')",
    "SELECT * FROM read_blob('/etc/hosts')",
    "SELECT load_extension('x')",
    "SELECT getenv('PATH')",
])
def test_rejects_file_and_network_functions(sql):
    with pytest.raises(GuardrailError):
        validate(sql)


def test_forces_limit_when_missing():
    fixed = validate("SELECT * FROM transfers")
    assert fixed.endswith("LIMIT 500")
    assert "LIMIT 500" in fixed


def test_forces_limit_on_with_query():
    fixed = validate("WITH x AS (SELECT 1 AS a) SELECT a FROM x")
    assert fixed.endswith("LIMIT 500")


def test_keeps_existing_limit():
    fixed = validate("SELECT * FROM transfers LIMIT 3")
    assert fixed == "SELECT * FROM transfers LIMIT 3"
    assert fixed.count("LIMIT") == 1


def test_allows_plain_select_and_with():
    assert validate("SELECT count(*) FROM transfers").startswith("SELECT")
    assert validate("WITH d AS (SELECT 1) SELECT * FROM d").startswith("WITH")


def test_strips_trailing_semicolon_only():
    fixed = validate("SELECT 1;")
    assert fixed == "SELECT 1\nLIMIT 500"


def test_rejects_empty_and_garbage():
    with pytest.raises(GuardrailError):
        validate("   ")
    with pytest.raises(GuardrailError):
        validate("")
    with pytest.raises(GuardrailError):
        validate(";")