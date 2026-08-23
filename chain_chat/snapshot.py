"""chain-chat — bundled snapshot generation.

Builds the offline, deterministic Ethereum transfer snapshot that powers the
whole app: USDC / UNI / WETH transfer events plus labeled addresses and token
metadata. The data is *synthetic* (testnet-style): no real mainnet funds,
generated offline from a fixed seed so every snapshot is reproducible.

Output layout (default: data/snapshot/):
    transfers.parquet   one row per transfer event
    labels.parquet      address -> human label + category
    tokens.parquet      token metadata incl. a static reference USD price
    manifest.json       seed, date range, counts, schema, policy note
    chainchat.db        compiled DuckDB database (read-only runtime)

The compiled chainchat.db is what the query layer opens in read-only mode;
the parquet files are the transparent, diffable artifacts.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import random
from pathlib import Path

import duckdb
import pandas as pd

TOKENS = [
    {"token": "usdc", "symbol": "USDC", "name": "USD Coin",
     "usd_reference_price": 1.00, "decimals": 6},
    {"token": "uni", "symbol": "UNI", "name": "Uniswap",
     "usd_reference_price": 8.50, "decimals": 18},
    {"token": "weth", "symbol": "WETH", "name": "Wrapped Ether",
     "usd_reference_price": 3150.00, "decimals": 18},
]

# address -> (label, category). Synthetic stand-ins for recognizable
# mainnet entities — clearly labeled as such in the README.
LABELS = [
    ("Binance Hot Wallet 14", "exchange"), ("Coinbase 9", "exchange"),
    ("Kraken 3", "exchange"), ("OKX Treasury", "exchange"),
    ("Bybit Hot Wallet", "exchange"), ("Crypto.com 2", "exchange"),
    ("Kucoin 4", "exchange"),
    ("Uniswap V3 Router 2", "defi"), ("Uniswap Universal Router", "defi"),
    ("Aave V2 LendingPool", "defi"), ("Compound cUSDC", "defi"),
    ("Curve 3pool", "defi"), ("1inch Aggregation Router", "defi"),
    ("MetaMask Swap Router", "defi"),
    ("Tether Treasury", "treasury"), ("USDC Treasury", "treasury"),
    ("Ethereum Foundation", "treasury"),
    ("Polygon Bridge", "bridge"), ("Arbitrum Bridge", "bridge"),
    ("Optimism Bridge", "bridge"), ("Wormhole Gateway", "bridge"),
    ("Lido Staking", "protocol"), ("Gnosis Safe (multisig)", "infra"),
    ("Jump Trading", "known"), ("Wintermute OTC", "known"),
]

# per-token amount distribution: lognormal(mu, sigma) in token units
AMOUNT_PDF = {
    "usdc": (7.31, 1.40),    # median ~ $1.5k, fat tail
    "uni": (6.40, 1.60),     # median ~ 600 UNI
    "weth": (0.05, 1.80),    # median ~ 1 WETH
}

TOKEN_WEIGHTS = {"usdc": 0.55, "uni": 0.25, "weth": 0.20}
EOA_COUNT = 30
BLOCKS_PER_DAY = 7200
START_BLOCK = 21_000_000
DEFAULT_START = dt.date(2026, 4, 26)
DEFAULT_DAYS = 120
DEFAULT_PER_DAY = 1000


def _addr(seed: str) -> str:
    return "0x" + hashlib.sha256(seed.encode()).hexdigest()[:40]


def _eoas(seed: int) -> list[str]:
    return [_addr(f"{seed}:eoa:{i}") for i in range(EOA_COUNT)]


def labeled_addresses() -> list[dict]:
    out = []
    for label, category in LABELS:
        out.append({"address": _addr(f"label:{label}"), "label": label,
                    "category": category})
    return out


def _pick(rng: random.Random, pool: list[str], weights: list[float]) -> str:
    return rng.choices(pool, weights=weights, k=1)[0]


def build_snapshot(out_dir: str | Path, seed: int = 42, days: int = DEFAULT_DAYS,
                   per_day: int = DEFAULT_PER_DAY,
                   start: dt.date | None = None) -> dict:
    """Generate the full snapshot into out_dir. Returns the manifest dict."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    start = start or DEFAULT_START

    labels = labeled_addresses()
    exchanges = [l["address"] for l in labels if l["category"] == "exchange"]
    defi = [l["address"] for l in labels if l["category"] == "defi"]
    orgs = [l["address"] for l in labels
            if l["category"] in ("treasury", "bridge", "protocol", "infra", "known")]
    eoas = _eoas(seed)
    all_addrs = [l["address"] for l in labels] + eoas

    rows: list[dict] = []
    seq = 0
    for d in range(days):
        day = start + dt.timedelta(days=d)
        count = max(50, int(per_day * rng.gauss(1.0, 0.08)))
        for j in range(count):
            token = rng.choices(list(TOKEN_WEIGHTS), weights=list(TOKEN_WEIGHTS.values()), k=1)[0]
            mu, sigma = AMOUNT_PDF[token]
            amount = rng.lognormvariate(mu, sigma)
            amount = round(amount, {"usdc": 2, "uni": 4, "weth": 6}[token])

            # busy-day clustering + a "night" lull
            hour = rng.choice([*([int(rng.gauss(15.5, 3.5))] * 6),
                               *([int(rng.gauss(3.0, 2.0))] * 1)])
            minute = rng.randint(0, 59)
            ts = dt.datetime.combine(day, dt.time(hour=max(0, min(23, hour)),
                                                  minute=minute, second=rng.randint(0, 59)))

            sender_pool = exchanges + eoas + defi + orgs
            sender_w = [0.35] * len(exchanges) + [0.35] * len(eoas) + \
                       [0.18] * len(defi) + [0.12] * len(orgs)
            receiver_pool = exchanges + eoas + defi + orgs
            receiver_w = [0.40] * len(exchanges) + [0.25] * len(eoas) + \
                         [0.22] * len(defi) + [0.13] * len(orgs)
            sender = _pick(rng, sender_pool, sender_w)
            receiver = _pick(rng, receiver_pool, receiver_w)
            for _ in range(6):
                if sender != receiver:
                    break
                sender = _pick(rng, sender_pool, sender_w)
                receiver = _pick(rng, receiver_pool, receiver_w)

            block = START_BLOCK + d * BLOCKS_PER_DAY + rng.randint(0, BLOCKS_PER_DAY - 1)
            rows.append({
                "tx_hash": f"0x{seq:064x}",
                "block_number": block,
                "ts": ts,
                "token": token,
                "amount": amount,
                "from_address": sender,
                "to_address": receiver,
            })
            seq += 1

    transfers = pd.DataFrame(rows)
    labels_df = pd.DataFrame(labels)
    tokens_df = pd.DataFrame(TOKENS)

    transfers_path = out / "transfers.parquet"
    labels_path = out / "labels.parquet"
    tokens_path = out / "tokens.parquet"
    transfers.to_parquet(transfers_path, index=False)
    labels_df.to_parquet(labels_path, index=False)
    tokens_df.to_parquet(tokens_path, index=False)

    manifest = {
        "generator": "chain_chat.snapshot.build_snapshot (scripts/fetch_parquet.py)",
        "seed": seed,
        "days": days,
        "per_day": per_day,
        "start_date": start.isoformat(),
        "end_date": (start + dt.timedelta(days=days - 1)).isoformat(),
        "transfers": len(rows),
        "labels": len(labels),
        "tokens": len(TOKENS),
        "policy": ("synthetic testnet-style data — no real mainnet funds; "
                   "regenerate with scripts/fetch_parquet.py"),
        "schema": {
            "transfers": ["tx_hash", "block_number", "ts", "token",
                          "amount", "from_address", "to_address"],
            "labels": ["address", "label", "category"],
            "tokens": ["token", "symbol", "name", "usd_reference_price",
                       "decimals"],
        },
        "files": ["transfers.parquet", "labels.parquet", "tokens.parquet",
                  "chainchat.db"],
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")

    _compile_db(out, transfers_path, labels_path, tokens_path)
    return manifest


def _compile_db(out: Path, transfers_path: Path, labels_path: Path,
                tokens_path: Path) -> None:
    """Compile the parquet files into a single DuckDB database that the
    runtime opens in read-only mode."""
    db_path = str(out / "chainchat.db")
    con = duckdb.connect(db_path)
    try:
        con.execute("CREATE TABLE transfers AS "
                    "SELECT * FROM read_parquet(?)", [str(transfers_path)])
        con.execute("CREATE TABLE labels AS "
                    "SELECT * FROM read_parquet(?)", [str(labels_path)])
        con.execute("CREATE TABLE tokens AS "
                    "SELECT * FROM read_parquet(?)", [str(tokens_path)])
    finally:
        con.close()


def snapshot_size(out_dir: str | Path) -> int:
    """Total bytes of the generated snapshot files."""
    out = Path(out_dir)
    return sum(p.stat().st_size for p in out.glob("*")
               if p.is_file() and p.name != "manifest.json")