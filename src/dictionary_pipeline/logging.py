"""
logging.py — append-only JSONL transformation log.

Every stage that mutates data writes events here. The log becomes the
`automated_changes` tab in the final Excel export.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class TransformationLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    def log(
        self,
        stage: str,
        event: str,
        rows_affected: int = 0,
        details: dict[str, Any] | None = None,
    ) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "event": event,
            "rows_affected": rows_affected,
            "details": details or {},
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]
