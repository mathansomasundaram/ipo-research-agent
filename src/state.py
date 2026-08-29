from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .utils import read_json, write_json


class ProcessedIPOStore:
    def __init__(self, path: Path, retention_days: int = 15) -> None:
        self.path = path
        self.retention_days = retention_days
        self.data: dict[str, Any] = read_json(path, default={"processed": {}})
        self.data.setdefault("processed", {})

    def cleanup(self, now: datetime) -> int:
        cutoff = now.astimezone(timezone.utc) - timedelta(days=self.retention_days)
        processed = self.data["processed"]
        to_delete: list[str] = []

        for ipo_id, record in processed.items():
            timestamp = record.get("updated_at") or record.get("processed_at")
            if not timestamp:
                continue
            try:
                parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
            except ValueError:
                continue
            if parsed.astimezone(timezone.utc) < cutoff:
                to_delete.append(ipo_id)

        for ipo_id in to_delete:
            del processed[ipo_id]
        if to_delete:
            self.save()
        return len(to_delete)

    def should_skip(self, ipo_id: str) -> bool:
        record = self.data["processed"].get(ipo_id) or {}
        return record.get("status") == "EMAIL_SENT"

    def mark(self, ipo_id: str, status: str, now: datetime, **extra: Any) -> None:
        self.data["processed"][ipo_id] = {
            "status": status,
            "updated_at": now.astimezone(timezone.utc).isoformat(),
            **extra,
        }
        self.save()

    def save(self) -> None:
        write_json(self.path, self.data)
