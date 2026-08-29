from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.state import ProcessedIPOStore


def test_state_retention_and_skip_logic(tmp_path: Path):
    path = tmp_path / "processed_ipos.json"
    store = ProcessedIPOStore(path, retention_days=15)
    now = datetime(2026, 8, 28, 12, 30, tzinfo=timezone.utc)

    store.mark("old", "EMAIL_SENT", now - timedelta(days=16))
    store.mark("sent", "EMAIL_SENT", now)
    store.mark("failed", "FAILED", now)

    removed = store.cleanup(now)

    assert removed == 1
    assert store.should_skip("sent") is True
    assert store.should_skip("failed") is False
    assert "old" not in store.data["processed"]
