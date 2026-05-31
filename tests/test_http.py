"""Tests for shared HTTP utilities and fetcher strategy layer."""
import time

from collectors.fetchers import ApiFetcher, HttpFetcher, SourceFetcher
from collectors.utils.http import HttpConfig, RateLimiter, build_session


def test_build_session_has_retries_and_ua():
    s = build_session(HttpConfig())
    assert s.headers.get("User-Agent")
    adapter = s.get_adapter("https://example.com")
    assert adapter.max_retries.total == 3


def test_rate_limiter_enforces_interval():
    rl = RateLimiter(min_interval_sec=0.2)
    url = "https://example.com/a"
    rl.wait(url)  # first call: no wait
    start = time.monotonic()
    rl.wait(url)  # second call: should wait ~0.2s
    elapsed = time.monotonic() - start
    assert elapsed >= 0.18


def test_rate_limiter_per_domain_independent():
    rl = RateLimiter(min_interval_sec=0.3)
    rl.wait("https://a.com/x")
    start = time.monotonic()
    rl.wait("https://b.com/y")  # 다른 도메인 → 대기 없음
    assert time.monotonic() - start < 0.1


def test_fetchers_implement_interface():
    assert issubclass(HttpFetcher, SourceFetcher)
    assert issubclass(ApiFetcher, SourceFetcher)
    for cls in (HttpFetcher, ApiFetcher):
        f = cls.__new__(cls)
        assert hasattr(f, "fetch_text") and hasattr(f, "fetch_json")
