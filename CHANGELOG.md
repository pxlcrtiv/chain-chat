# Changelog

All notable changes to chain-chat are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Roadmap idea #5 (Tier 2 flagship): ask on-chain history in plain English.
- Offline-first architecture: bundled deterministic DuckDB/parquet snapshot,
  zero API keys required for the demo.
- `chain_chat/snapshot.py` + `scripts/fetch_parquet.py`: seeded synthetic
  USDC / UNI / WETH transfer snapshot (transfers + labels + tokens parquet,
  compiled read-only `chainchat.db`, manifest).
- `chain_chat/db.py`: read-only DuckDB query layer — parameter binding,
  statement guardrails, forced LIMIT, wall-clock timeout with interrupt,
  truncation flag.
- `chain_chat/guardrails.py`: read-only SQL enforcement (SELECT/WITH only,
  no stacked statements, no file/network functions).
- `chain_chat/nl2sql.py`: schema-aware NL→SQL pipeline with an
  OpenAI-compatible LLM (execute-and-validate rewrite loop, error feedback)
  and a deterministic canned fallback answering the three canonical
  questions offline.
- `chain_chat/canned.py`: the three flagship canned answers, computed live
  from the snapshot.
- `chain_chat/golden.py`: 7 golden question→SQL regression queries.
- `chain_chat/live.py`: optional BigQuery live mode contract (requires a
  user-provided GCP credential; documented, not bundled).
- `app.py`: Streamlit chat UI with canned-question shortcuts, SQL + results
  expanders, offline/LLM engine indicator.
- Test suite: 65 pytest tests (guardrails, injection, timeout, golden
  queries, deterministic mock LLM, snapshot determinism, CLI paths).
- Daily Green automation: `scripts/daily_update.py` + `scripts/tips_pool.json`
  (24 curated on-chain data/analytics tips), idempotent dated commits,
  launchd + GitHub Actions fallback.
- Project docs: README, CONTRIBUTING, CHANGELOG, MIT LICENSE, CI workflow
  (unit tests + snapshot determinism + offline demo smoke + lint).

## [0.1.0] — 2026-08-23

Initial public release.

- Demo (`streamlit run app.py`, zero keys, ≤ 2 min): the three canned
  questions answer offline in seconds.
- Repo published at https://github.com/pxlcrtiv/chain-chat (public).