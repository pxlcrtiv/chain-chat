# chain-chat data tips of the day

> Maintained by `scripts/daily_update.py` (Daily Green automation) — one
> dated, non-empty on-chain data/analytics tip per day, rotated from the
> pool in `scripts/tips_pool.json`. Pause by creating a `.daily-pause`
> file in the repo root, or unload the scheduler job (see README,
> Daily Green).


## 2026-08-23 — Tip of the day: Normalize token amounts before you compare anything

Transfer amounts live in token units with wildly different decimals (USDC=6, UNI/WETH=18). Always multiply by tokens.usd_reference_price when comparing volume across tokens — raw amount sums are apples-to-oranges. In chain-chat: `SELECT token, ROUND(SUM(amount * t.usd_reference_price), 2) AS usd_volume FROM transfers x JOIN tokens t ON t.token = x.token GROUP BY 1 ORDER BY 2 DESC`.

> `python -c "from chain_chat.golden import run_golden; print(run_golden(ChainDB('data/snapshot')))"`


## 2026-08-24 — Tip of the day: "Yesterday" is a window, not a constant

On-chain datasets lag (indexers, finality, timezones). Hardcoding CURDATE() in analytics SQL silently excludes recent blocks. Anchor to the data itself: `WITH d AS (SELECT CAST(max(ts) AS DATE) - INTERVAL 1 DAY AS day FROM transfers)` — that is exactly what chain-chat's flagship question does.

> `duckdb data/snapshot/chainchat.db "WITH d AS (SELECT CAST(max(ts) AS DATE) - INTERVAL 1 DAY AS day FROM transfers) SELECT day FROM d"`


## 2026-08-25 — Tip of the day: Labeled addresses are joins, not constants

Don't hardcode 0x addresses in your queries. Keep an address → label registry (chain-chat ships labels.parquet) and JOIN on it: `SELECT l.label, COUNT(*) FROM transfers x JOIN labels l ON l.address = x.from_address GROUP BY 1 ORDER BY 2 DESC LIMIT 5`. Labels drift; joins don't.

> `duckdb data/snapshot/chainchat.db "SELECT category, COUNT(*) FROM labels GROUP BY 1 ORDER BY 2 DESC"`


## 2026-08-26 — Tip of the day: ERC-20 Transfer events: sender vs. spender

The Transfer event's `from` is the token holder, not the msg.sender. When someone burns allowance via a router, Transfer(from=holder, to=router). Analysts who treat `from` as "the actor" misattribute flows — cross-reference the transaction's actual sender for the true initiator.

> `SELECT from_address, to_address, COUNT(*) AS n FROM transfers GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 10`


## 2026-08-27 — Tip of the day: Volume ≠ liquidity

A token with $100M transfer volume can still be deeply illiquid if most of it ping-pongs between two hot wallets. When ranking 'most moved', look past the top line: count distinct counterparties (COUNT(DISTINCT to_address)) and distribution (stddev) before calling something liquid.

> `SELECT token, COUNT(DISTINCT to_address) AS counterparties FROM transfers GROUP BY 1`


## 2026-08-28 — Tip of the day: Run a trend, not a point-in-time number

Single-day aggregates mislead. Report 7-day windows when answering 'how much moved': `WITH win AS (SELECT max(ts) - INTERVAL 7 DAY AS lo FROM transfers) SELECT CAST(ts AS DATE) AS day, COUNT(*) FROM transfers, win WHERE ts >= win.lo GROUP BY 1 ORDER BY 1` — 7 bars tell you more than 1 number.

> `duckdb data/snapshot/chainchat.db "WITH win AS (SELECT max(ts) - INTERVAL 7 DAY AS lo FROM transfers) SELECT CAST(ts AS DATE) AS day, COUNT(*) AS n FROM transfers, win WHERE ts >= win.lo GROUP BY 1 ORDER BY 1"`


## 2026-08-29 — Tip of the day: Query parameters defeat injection — every time

Never interpolate user input into SQL strings. Binding via ? or $name keeps hostile input data, not code: `SELECT * FROM transfers WHERE token = ?` with param "usdc' OR '1'='1" returns zero rows instead of wrecking your query. chain-chat enforces this in chain_chat/db.py.

> `duckdb data/snapshot/chainchat.db "PREPARE q AS SELECT COUNT(*) FROM transfers WHERE token = ?"`


## 2026-08-30 — Tip of the day: DuckDB reads parquet directly — skip the ETL

For one-off analytics you don't need a warehouse. `duckdb -c "SELECT COUNT(*) FROM 'transfers.parquet'"` queries the file in place, vectorized, often faster than a loaded DB. chain-chat compiles a read-only .db for safety, but the parquet files are the source of truth.

> `duckdb -c "SELECT COUNT(*) FROM 'data/snapshot/transfers.parquet'"`


## 2026-08-31 — Tip of the day: Checkpoint: block ranges are your timezone

Ethereum produces ~7,200 blocks/day. Financial analytics should bucket by block, not wall-clock: `(block_number / 7200)` gives you a stable day bucket that survives indexer delays, reorgs and DST. Use timestamps for display, blocks for math.

> `SELECT (block_number / 7200) AS day_bucket, COUNT(*) FROM transfers GROUP BY 1 ORDER BY 1 DESC LIMIT 7`


## 2026-09-01 — Tip of the day: Suspicious flow? Look at the recipient's history

A single large transfer into an EOA is noise; the same EOA receiving 50 transfers from 50 different tokens in 1 hour is a pattern (sweeper bot, mixer entry). Windowed counterparty counts per address are the cheapest wash-trading/sweep detector there is.

> `SELECT to_address, COUNT(DISTINCT token) AS tokens_in FROM transfers GROUP BY 1 HAVING COUNT(DISTINCT token) >= 3 ORDER BY 2 DESC LIMIT 5`


## 2026-09-02 — Tip of the day: UNION ALL beats OR for disjoint buckets

When splitting flows by category (exchange vs defi vs bridge), UNION ALL of filtered subqueries is often clearer and lets DuckDB parallelize partitions — and it keeps each bucket's filter explicit for review, which matters when a human must audit the logic.

> `SELECT 'exchange' AS bucket, COUNT(*) FROM transfers x JOIN labels l ON l.address = x.to_address WHERE l.category = 'exchange' UNION ALL SELECT 'defi', COUNT(*) FROM transfers x JOIN labels l ON l.address = x.to_address WHERE l.category = 'defi'`

