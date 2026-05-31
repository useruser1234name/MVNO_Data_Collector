"""robots.txt 준수 및 크롤링 가드레일.

40+ 사업자·이통3사로 확장 시 차단·법적 리스크가 비선형 증가한다.
요금제는 공개 마케팅 정보이나, 기본적으로 robots를 준수하고 식별 가능한 UA와
도메인별 일일 요청 예산을 두어 지속가능성(차단 안 당하기)을 확보한다.
"""
from __future__ import annotations

import logging
import threading
import urllib.robotparser
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)

# 식별 가능한 UA(연락처 포함) — 운영 시 실제 연락처로 교체
IDENTIFIABLE_USER_AGENT = "MVNO-Data-Collector/1.0 (+contact: ops@example.com)"


class RobotsCache:
    """도메인별 robots.txt 파서 캐시."""

    def __init__(self, user_agent: str = IDENTIFIABLE_USER_AGENT) -> None:
        self.user_agent = user_agent
        self._cache: Dict[str, urllib.robotparser.RobotFileParser] = {}
        self._lock = threading.Lock()

    def _parser_for(self, url: str) -> urllib.robotparser.RobotFileParser:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        with self._lock:
            parser = self._cache.get(base)
            if parser is None:
                parser = urllib.robotparser.RobotFileParser()
                parser.set_url(urljoin(base, "/robots.txt"))
                try:
                    parser.read()
                except Exception as exc:  # noqa: BLE001 - robots 미존재/오류 시 허용 기본값
                    logger.warning("robots.txt read failed for %s: %s", base, exc)
                    parser = None  # 읽기 실패 시 허용(아래에서 처리)
                self._cache[base] = parser
            return parser

    def can_fetch(self, url: str) -> bool:
        parser = self._parser_for(url)
        if parser is None:
            return True  # robots를 읽지 못하면 보수적으로 허용(공개 정보 가정)
        return parser.can_fetch(self.user_agent, url)


@dataclass(slots=True)
class CrawlBudget:
    """도메인별 일일 요청 예산(과도한 부하/차단 방지)."""

    max_requests_per_domain: int = 5000
    _counts: Dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def allow(self, url: str) -> bool:
        domain = urlparse(url).netloc or url
        if self._counts[domain] >= self.max_requests_per_domain:
            logger.warning("Crawl budget exceeded for %s", domain)
            return False
        self._counts[domain] += 1
        return True
