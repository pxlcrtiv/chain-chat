#!/usr/bin/env python3
"""
chain-chat — regenerate the bundled offline snapshot.

Generates the deterministic, synthetic (testnet-style) USDC / UNI / WETH
transfer snapshot that chain-chat queries: transfers.parquet, labels.parquet,
tokens.parquet, manifest.json and a compiled chainchat.db (read-only runtime).

No API keys. No paid APIs. No real funds. Same seed ⇒ identical snapshot.

Usage:
    python scripts/fetch_parquet.py                     # default snapshot
    python scripts/fetch_parquet.py --seed 7 --days 30 --per-day 200
    python scripts/fetch_parquet.py --out /tmp/snap     # custom location
    python scripts/fetch_parquet.py --live              # optional BigQuery
                                                          mode (needs key)

--live requires a user-provided GCP credential (see chain_chat/live.py);
without one it fails fast with instructions. The offline snapshot is the
supported demo path.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from chain_chat.live import LiveModeUnavailable, fetch_live_transfers  # noqa: E402
from chain_chat.snapshot import DEFAULT_DAYS, DEFAULT_PER_DAY, build_snapshot, snapshot_size  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(REPO_ROOT / "data" / "snapshot"),
                    help="output directory (default: data/snapshot)")
    ap.add_argument("--seed", type=int, default=42,
                    help="RNG seed — same seed, same snapshot (default 42)")
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS,
                    help=f"days of history (default {DEFAULT_DAYS})")
    ap.add_argument("--per-day", type=int, default=DEFAULT_PER_DAY,
                    help=f"transfers per day (default {DEFAULT_PER_DAY})")
    ap.add_argument("--start", type=dt.date.fromisoformat,
                    default=None, help="start date YYYY-MM-DD")
    ap.add_argument("--live", action="store_true",
                    help="try BigQuery live mode instead of synthetic "
                         "(requires user-provided GCP credential)")
    args = ap.parse_args()

    if args.live:
        try:
            fetch_live_transfers(args.out)
        except LiveModeUnavailable as exc:
            print(f"LIVE MODE UNAVAILABLE: {exc}")
            return 2
        return 0

    manifest = build_snapshot(args.out, seed=args.seed, days=args.days,
                              per_day=args.per_day, start=args.start)
    size_mb = snapshot_size(args.out) / 1_000_000
    print(f"OK — snapshot written to {args.out}")
    print(f"  seed={manifest['seed']}  window={manifest['start_date']} → "
          f"{manifest['end_date']}  ({manifest['days']} days)")
    print(f"  transfers={manifest['transfers']:,}  labels={manifest['labels']} "
          f"tokens={manifest['tokens']}")
    print(f"  total size ≈ {size_mb:.1f} MB (policy: synthetic testnet-style "
          "data, no real funds)")
    print("  run `streamlit run app.py` to chat with it")
    return 0


if __name__ == "__main__":
    sys.exit(main())