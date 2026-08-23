"""Golden query + snapshot determinism tests."""

import hashlib
import subprocess
import sys
from pathlib import Path

from chain_chat.golden import all_pass, run_golden
from chain_chat.snapshot import build_snapshot

REPO_ROOT = Path(__file__).resolve().parent.parent


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_all_golden_queries_pass(db):
    results = run_golden(db, timeout=15)
    assert all_pass(results), [r for r in results if not r["ok"]]
    assert len(results) == 7


def test_golden_queries_are_documented_questions():
    from chain_chat.golden import GOLDEN
    assert len(GOLDEN) >= 5
    for g in GOLDEN:
        assert g["question"] and g["sql"] and callable(g["check"])


def test_snapshot_is_deterministic(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    build_snapshot(a, seed=99, days=10, per_day=40)
    build_snapshot(b, seed=99, days=10, per_day=40)
    for f in ("transfers.parquet", "labels.parquet", "tokens.parquet",
              "manifest.json"):
        assert _sha(a / f) == _sha(b / f), f


def test_snapshot_differs_with_seed(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    build_snapshot(a, seed=1, days=10, per_day=40)
    build_snapshot(b, seed=2, days=10, per_day=40)
    assert _sha(a / "transfers.parquet") != _sha(b / "transfers.parquet")


def test_manifest_has_policy_and_schema(tmp_path):
    out = tmp_path / "snap"
    manifest = build_snapshot(out, seed=3, days=5, per_day=20)
    assert manifest["seed"] == 3
    assert manifest["transfers"] > 0
    assert "synthetic" in manifest["policy"]
    assert set(manifest["schema"]) == {"transfers", "labels", "tokens"}
    assert (out / "chainchat.db").exists()  # compiled read-only runtime DB


def test_fetch_parquet_cli(tmp_path):
    out = tmp_path / "cli_snap"
    r = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "fetch_parquet.py"),
         "--out", str(out), "--seed", "5", "--days", "5", "--per-day", "25"],
        capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stderr
    assert (out / "transfers.parquet").exists()
    assert "OK" in r.stdout


def test_fetch_parquet_live_mode_fails_fast_without_key(tmp_path):
    r = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "fetch_parquet.py"),
         "--out", str(tmp_path / "live"), "--live"],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 2
    assert "LIVE MODE UNAVAILABLE" in r.stdout