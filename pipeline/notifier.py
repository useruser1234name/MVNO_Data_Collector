"""Simple webhook notifier used by the orchestration layer."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Optional

import httpx


@dataclass(slots=True)
class WebhookConfig:
    url: str
    headers: Optional[Mapping[str, str]] = None
    timeout: float = 10.0


class WebhookNotifier:
    """Send JSON payloads to an HTTP endpoint."""

    def __init__(self, config: WebhookConfig) -> None:
        self._config = config

    def send(self, payload: Mapping[str, Any]) -> httpx.Response:
        response = httpx.post(
            self._config.url,
            data=json.dumps(payload, ensure_ascii=False),
            headers={"Content-Type": "application/json", **(self._config.headers or {})},
            timeout=self._config.timeout,
        )
        response.raise_for_status()
        return response
