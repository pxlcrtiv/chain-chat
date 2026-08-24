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

