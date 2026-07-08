"""사업자 카탈로그 로더 — config/vendors.yaml을 단일 진실원천으로 다룬다.

레지스트리·동적 DAG·모니터링이 이 카탈로그에서 파생된다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import yaml

DEFAULT_CATALOG_PATH = Path(__file__).resolve().parent.parent / "config" / "vendors.yaml"

VALID_GROUPS = {"mvno", "mno"}
VALID_COLLECTOR_TYPES = {"requests", "playwright", "api", "generic", "stub"}
VALID_ANTI_BOT = {"low", "medium", "high"}
# 수집기 등록이 필요 없는 타입(스캐폴딩/스텁)
NON_REGISTERED_TYPES = {"stub"}


@dataclass(slots=True)
class VendorEntry:
    key: str
    display_name: str
    group: str
    network: str
    collector_type: str
    enabled: bool
    anti_bot_level: str
    schedule: str
    expected_min_records: int = 0
    owner: str | None = None
    base_urls: List[str] = field(default_factory=list)
    policy_file: str | None = None  # generic 수집기용 셀렉터 정책 경로

    def __post_init__(self) -> None:
        if self.group not in VALID_GROUPS:
            raise ValueError(f"[{self.key}] invalid group: {self.group}")
        if self.collector_type not in VALID_COLLECTOR_TYPES:
            raise ValueError(f"[{self.key}] invalid collector_type: {self.collector_type}")
        if self.anti_bot_level not in VALID_ANTI_BOT:
            raise ValueError(f"[{self.key}] invalid anti_bot_level: {self.anti_bot_level}")

    @property
    def requires_registered_collector(self) -> bool:
        return self.collector_type not in NON_REGISTERED_TYPES

    @classmethod
    def from_mapping(cls, key: str, data: Dict[str, Any]) -> "VendorEntry":
        return cls(
            key=key,
            display_name=data.get("display_name", key),
            group=data.get("group", "mvno"),
            network=data.get("network", ""),
            collector_type=data.get("collector_type", "requests"),
            enabled=bool(data.get("enabled", False)),
            anti_bot_level=data.get("anti_bot_level", "low"),
            schedule=data.get("schedule", "0 0 * * *"),
            expected_min_records=int(data.get("expected_min_records", 0)),
            owner=data.get("owner"),
            base_urls=list(data.get("base_urls") or []),
            policy_file=data.get("policy_file"),
        )


@dataclass(slots=True)
class VendorCatalog:
    entries: Dict[str, VendorEntry]

    def get(self, key: str) -> VendorEntry:
        return self.entries[key]

    def all(self) -> List[VendorEntry]:
        return list(self.entries.values())

    def enabled(self) -> List[VendorEntry]:
        return [e for e in self.entries.values() if e.enabled]

    def by_group(self, group: str) -> List[VendorEntry]:
        return [e for e in self.entries.values() if e.group == group]

    @classmethod
    def load(cls, path: Path | None = None) -> "VendorCatalog":
        path = path or DEFAULT_CATALOG_PATH
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        vendors = raw.get("vendors") or {}
        if not isinstance(vendors, dict):
            raise ValueError("catalog 'vendors' must be a mapping")
        entries = {key: VendorEntry.from_mapping(key, data) for key, data in vendors.items()}
        return cls(entries=entries)


def load_catalog(path: Path | None = None) -> VendorCatalog:
    return VendorCatalog.load(path)
