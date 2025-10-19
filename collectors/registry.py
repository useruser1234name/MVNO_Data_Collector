"""Registry that keeps track of available collectors."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Type

from collectors.base import BaseCollector, CollectorConfig


@dataclass(frozen=True)
class CollectorMetadata:
    name: str
    module: str
    description: str | None = None


class CollectorRegistry:
    """Simple registry used to retrieve collector classes by name."""

    def __init__(self) -> None:
        self._registry: Dict[str, tuple[Type[BaseCollector], CollectorMetadata]] = {}

    def register(
        self,
        key: str,
        collector_cls: Type[BaseCollector],
        *,
        description: str | None = None,
        module: str | None = None,
    ) -> None:
        metadata = CollectorMetadata(name=key, module=module or collector_cls.__module__, description=description)
        self._registry[key] = (collector_cls, metadata)

    def available(self) -> Iterable[str]:
        return sorted(self._registry)

    def create(self, key: str, config: CollectorConfig) -> BaseCollector:
        collector_cls, _ = self._registry[key]
        return collector_cls(config)

    def metadata(self, key: str) -> CollectorMetadata:
        return self._registry[key][1]


registry = CollectorRegistry()
