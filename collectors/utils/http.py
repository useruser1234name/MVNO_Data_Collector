"""공통 HTTP 인프라 — 세션/재시도/레이트리미트/UA 풀의 단일 출처.

벤더마다 build_session()을 복붙하던 것을 통합하고, 안티봇 대응(백오프·UA 로테이션·
도메인별 속도제한)을 한 곳에 모은다. 40+ 사업자 동시 실행 시 동일 호스팅 그룹에
대한 과부하를 도메인 단위 레이트리미터로 방지한다.
"""
from __future__ import annotations

import itertools
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]

DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Connection": "keep-alive",
}


class RateLimiter:
    """도메인별 최소 요청 간격을 강제하는 단순 레이트리미터(스레드 안전)."""

    def __init__(self, min_interval_sec: float = 0.5) -> None:
        self.min_interval = min_interval_sec
        self._last: Dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, url: str) -> None:
        domain = urlparse(url).netloc or url
        with self._lock:
            now = time.monotonic()
            last = self._last.get(domain, 0.0)
            elapsed = now - last
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self._last[domain] = time.monotonic()


@dataclass(slots=True)
class HttpConfig:
    total_retries: int = 3
    backoff_factor: float = 0.5
    timeout: float = 25.0
    min_interval_sec: float = 0.5
    user_agents: list[str] = field(default_factory=lambda: list(DEFAULT_USER_AGENTS))
    extra_headers: dict[str, str] = field(default_factory=dict)


def build_session(config: Optional[HttpConfig] = None) -> requests.Session:
    config = config or HttpConfig()
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    if config.user_agents:
        session.headers["User-Agent"] = config.user_agents[0]
    session.headers.update(config.extra_headers)
    retries = Retry(
        total=config.total_retries,
        backoff_factor=config.backoff_factor,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST"),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def looks_blocked(response: requests.Response) -> bool:
    """차단/봇 챌린지 의심 응답 감지(휴리스틱)."""
    if response.status_code in (403, 429):
        return True
    text = (response.text or "")[:2000].lower()
    markers = ("captcha", "are you a robot", "비정상적인 접근", "보안문자", "access denied")
    return any(m in text for m in markers)
