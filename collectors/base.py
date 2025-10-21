"""Core abstractions shared by all collectors."""
from __future__ import annotations

import abc
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, List, Sequence

from collectors.policy import FieldPolicySet
from collectors.utils.output import OutputManager
from schemas.plan_record import PlanRecord


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CollectorConfig:
    """Configuration passed to every collector implementation."""

    name: str
    output_dir: Path
    concurrency: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)
    field_policy: FieldPolicySet | None = None


class BaseCollector(abc.ABC):
    """Base class that defines the life-cycle for all collectors."""

    def __init__(self, config: CollectorConfig) -> None:
        self.config = config
        self._output_manager = OutputManager(config.output_dir, config.name)

    @property
    def field_policy(self) -> FieldPolicySet | None:
        """Return the field policy associated with this collector, if any."""
        return self.config.field_policy

    async def run(self) -> Sequence[PlanRecord]:
        """Execute the collector and return the parsed records."""
        logger.info("Starting collector", extra={"collector": self.config.name})
        start = datetime.utcnow()
        await self.setup()
        try:
            raw_entries = await self.fetch_entries()
            records = await self.parse_entries(raw_entries)
            await self.persist_records(records)
            duration = (datetime.utcnow() - start).total_seconds()
            logger.info(
                "Collector finished",
                extra={
                    "collector": self.config.name,
                    "duration_seconds": duration,
                    "records": len(records),
                },
            )
            return records
        finally:
            await self.teardown()

    async def setup(self) -> None:
        """Optional asynchronous setup before fetching data."""

    async def teardown(self) -> None:
        """Optional asynchronous cleanup after the collector completes."""

    @abc.abstractmethod
    async def fetch_entries(self) -> Iterable[Any]:
        """Retrieve raw payloads that will later be parsed into plan records."""

    @abc.abstractmethod
    async def parse_entries(self, entries: Iterable[Any]) -> List[PlanRecord]:
        """Transform vendor specific payloads into :class:`PlanRecord` objects."""

    async def persist_records(self, records: Sequence[PlanRecord]) -> None:
        """Persist records via the output manager and record metadata."""
        payload = [record.to_dict() for record in records]
        meta = {
            "collector": self.config.name,
            "collected_at": datetime.utcnow().isoformat(),
            "metadata": self.config.metadata,
        }
        if self.field_policy is not None:
            meta["field_policy"] = self.field_policy.describe()
        await asyncio.to_thread(self._output_manager.save_records, payload, meta)

    async def save_raw_payload(self, payload: Any, name: str = "raw.json") -> Path:
        """Persist raw payloads for troubleshooting without blocking the loop."""
        return await asyncio.to_thread(self._output_manager.save_raw_payload, payload, name)
