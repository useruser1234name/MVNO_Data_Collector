"""수집 전략(Fetcher) 계층 — '어떻게 가져오는가'를 수집기에서 분리한다.

requests/playwright/api 등 이질적 소스를 동일한 인터페이스로 추상화하여,
안티봇·레이트리미트·UA 로테이션 같은 횡단 관심사를 한 곳에 모은다.
"""
from collectors.fetchers.base import SourceFetcher
from collectors.fetchers.http import ApiFetcher, HttpFetcher

__all__ = ["SourceFetcher", "HttpFetcher", "ApiFetcher"]
