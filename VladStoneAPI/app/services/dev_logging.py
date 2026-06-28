from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEV_DIR = PROJECT_ROOT / ".dev"


def append_dev_log(file_name: str, event: str, payload: dict[str, Any] | None = None) -> None:
    DEV_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": datetime.now(UTC).isoformat(),
        "event": event,
        "payload": payload or {},
    }
    with (DEV_DIR / file_name).open("a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
