"""requests 기반 Fetcher 전략(HTTP/JSON API)."""
from __future__ import annotations

import logging
from typing import Any, Optional

from collectors.fetchers.base import SourceFetcher
from collectors.utils.http import HttpConfig, RateLimiter, build_session, looks_blocked

logger = logging.getLogger(__name__)


class HttpFetcher(SourceFetcher):
    """공유 세션 + 레이트리미터로 HTML/텍스트를 가져오는 전략."""

    def __init__(self, config: Optional[HttpConfig] = None, rate_limiter: Optional[RateLimiter] = None) -> None:
        self.config = config or HttpConfig()
        self.session = build_session(self.config)
        self.rate_limiter = rate_limiter or RateLimiter(self.config.min_interval_sec)

    def fetch_text(self, url: str, **kwargs: Any) -> str:
        self.rate_limiter.wait(url)
        response = self.session.get(url, timeout=self.config.timeout, **kwargs)
        if not response.encoding or response.encoding.lower() == "iso-8859-1":
            response.encoding = "utf-8"
        if looks_blocked(response):
            logger.warning("Possible bot-block/challenge detected for %s (status=%s)", url, response.status_code)
        response.raise_for_status()
        return response.text

    def fetch_json(self, url: str, **kwargs: Any) -> Any:
        self.rate_limiter.wait(url)
        response = self.session.get(url, timeout=self.config.timeout, **kwargs)
        response.raise_for_status()
        return response.json()

    def close(self) -> None:
        self.session.close()


class ApiFetcher(HttpFetcher):
    """내부 JSON API 우선 전략. fetch_text 대신 fetch_json을 주 경로로 사용."""

    def fetch_text(self, url: str, **kwargs: Any) -> str:
        self.rate_limiter.wait(url)
        response = self.session.get(url, timeout=self.config.timeout, **kwargs)
        response.raise_for_status()
        return response.text
