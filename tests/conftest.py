import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from chain_chat.db import ChainDB  # noqa: E402
from chain_chat.snapshot import build_snapshot  # noqa: E402


@pytest.fixture(scope="session")
def snapshot_dir(tmp_path_factory):
    """Small deterministic snapshot shared by the whole session (~1800 rows)."""
    out = tmp_path_factory.mktemp("snapshot")
    build_snapshot(out, seed=7, days=30, per_day=60)
    return out


@pytest.fixture(scope="session")
def db(snapshot_dir):
    conn = ChainDB(snapshot_dir)
    yield conn
    conn.close()