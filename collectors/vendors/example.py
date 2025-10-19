"""Example collector implementation demonstrating the base interface."""
from __future__ import annotations

import logging
from typing import Any, Iterable, List

from collectors.base import BaseCollector
from collectors.registry import registry
from schemas.plan_record import PlanRecord

logger = logging.getLogger(__name__)


class ExampleCollector(BaseCollector):
    """A minimal collector that returns an empty result set."""

    async def fetch_entries(self) -> Iterable[Any]:
        return []

    async def parse_entries(self, entries: Iterable[Any]) -> List[PlanRecord]:
        # Example of how to inspect configured field policies for documentation purposes.
        if self.field_policy is not None:
            price_rules = self.field_policy.selectors_for("PRICE")
            for rule in price_rules:
                # In a real collector this loop would drive how we extract values.
                # This stub simply logs the available selectors for reference.
                logger.info(
                    "Selector configured for PRICE",
                    extra={
                        "collector": self.config.name,
                        "selector": rule.selector,
                        "attribute": rule.attribute,
                        "reason": rule.reason,
                    },
                )
        return []


registry.register("example", ExampleCollector, description="Stub collector used for smoke tests")
