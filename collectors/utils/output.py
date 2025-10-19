"""Utility helpers for persisting collector outputs."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


class OutputManager:
    """Persist collector outputs following repository conventions."""

    def __init__(self, base_dir: Path, collector_name: str) -> None:
        self.base_dir = Path(base_dir)
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        self.collector_dir = self.base_dir / collector_name / timestamp
        self.collector_dir.mkdir(parents=True, exist_ok=True)

    def save_records(self, records: Iterable[dict[str, Any]], metadata: dict[str, Any]) -> Path:
        """Write normalized records and metadata to disk."""
        records_path = self.collector_dir / "records.jsonl"
        with records_path.open("w", encoding="utf-8") as fh:
            for record in records:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")

        meta_path = self.collector_dir / "metadata.json"
        with meta_path.open("w", encoding="utf-8") as fh:
            json.dump(metadata, fh, ensure_ascii=False, indent=2)
        return records_path

    def save_raw_payload(self, payload: Any, name: str) -> Path:
        """Persist a raw payload for debugging."""
        filename = name if name.endswith(('.json', '.txt', '.html')) else f"{name}.txt"
        path = self.collector_dir / filename
        if isinstance(payload, (dict, list)):
            serialized = json.dumps(payload, ensure_ascii=False, indent=2)
            path.write_text(serialized, encoding="utf-8")
        else:
            path.write_text(str(payload), encoding="utf-8")
        return path
