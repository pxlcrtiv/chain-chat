# Contributing to chain-chat

Thanks for wanting to help! chain-chat is a small, offline-first project:
an LLM that answers questions about a bundled Ethereum transfer snapshot.
Keep it small, deterministic, and keyless-by-default.

## Ground rules

- **Offline is the demo.** Every feature must work with zero API keys.
  The deterministic canned answers and the bundled snapshot are not
  fallbacks — they are the product. LLM features are an enhancement on top.
- **Never block on keys.** Code paths that need credentials must fail fast
  with instructions, never hang, and never be required for tests or CI.
- **Testnet-only data policy.** No real mainnet funds anywhere. The bundled
  snapshot is synthetic (seeded, reproducible); live connectors read public
  data only.
- **Deterministic tests.** Tests must pass offline, in CI, and on any
  machine. Same seed → same snapshot → same query results.

## Development loop

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest
python scripts/fetch_parquet.py            # regenerate the snapshot
python -m pytest tests/ -q                 # 65 tests, all offline
streamlit run app.py                       # chat with it
```

## Where things live

| Path                     | What it is                                              |
|--------------------------|---------------------------------------------------------|
| `chain_chat/snapshot.py` | seeded synthetic snapshot generator                     |
| `chain_chat/db.py`       | read-only DuckDB query layer (timeout + LIMIT guards)   |
| `chain_chat/guardrails.py` | SQL injection / write-statement guardrails            |
| `chain_chat/nl2sql.py`   | NL→SQL pipeline (LLM + execute-and-validate rewrite)    |
| `chain_chat/canned.py`   | deterministic zero-key answers for the 3 canonical Qs   |
| `chain_chat/golden.py`   | golden question→SQL regression queries                  |
| `app.py`                 | Streamlit chat UI                                       |
| `scripts/fetch_parquet.py` | snapshot CLI (`--live` requires user-provided creds)  |
| `scripts/daily_update.py` | Daily Green automation (one dated commit per day)      |

## Good first improvements

- Add a fourth canned question (update `canned.py` + tests + README).
- Add golden queries for new insight shapes (breakout by hour, bridge flows).
- Improve the LLM system prompt (few-shot examples live in `nl2sql.py`).
- Wire the BigQuery live connector (`chain_chat/live.py` has the contract).

## Pull requests

1. Branch from `main`; keep changes focused.
2. Add or update tests — the suite must stay green (`python -m pytest -q`).
3. Update `CHANGELOG.md` (Unreleased section).
4. PR description: what changed, how it was verified, screenshots for UI.

## Releasing

Keep `CHANGELOG.md` current; tag versions with `git tag vX.Y.Z` and push.
No release machinery, no paid services — by design.