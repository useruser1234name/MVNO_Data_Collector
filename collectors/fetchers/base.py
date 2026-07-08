"""Fetcher 전략 인터페이스."""
from __future__ import annotations

import abc
from typing import Any


class SourceFetcher(abc.ABC):
    """원본 소스에서 콘텐츠를 가져오는 전략의 공통 인터페이스."""

    @abc.abstractmethod
    def fetch_text(self, url: str, **kwargs: Any) -> str:
        """주어진 URL의 텍스트(HTML 등)를 반환한다."""

    def fetch_json(self, url: str, **kwargs: Any) -> Any:
        """기본 구현: 텍스트를 JSON으로 파싱. API 전략에서 오버라이드 가능."""
        import json

        return json.loads(self.fetch_text(url, **kwargs))

    def close(self) -> None:
        """리소스 정리(선택)."""
