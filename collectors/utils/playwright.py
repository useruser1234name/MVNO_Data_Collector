"""Shared Playwright helpers used by collectors (스텔스 컨텍스트 포함).

이통3사 등 강한 안티봇 사이트 대응을 위해 navigator.webdriver 패치, locale/timezone,
UA, viewport, 리소스 차단, storage_state(세션 재사용) 옵션을 한 곳에서 제공한다.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

# 헤드리스 자동화 탐지 신호를 줄이는 init script(군비경쟁이라 완벽하진 않음).
STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['ko-KR', 'ko']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
window.chrome = window.chrome || { runtime: {} };
"""

# 속도/차단확률을 줄이기 위해 차단할 리소스 유형
_BLOCKED_RESOURCE_TYPES = {"image", "media", "font"}


def stealth_context_options(
    user_agent: Optional[str] = None,
    locale: str = "ko-KR",
    timezone_id: str = "Asia/Seoul",
    viewport: tuple[int, int] = (1366, 768),
    storage_state: Optional[str] = None,
) -> dict[str, Any]:
    """new_context에 전달할 옵션 딕셔너리를 구성(순수 함수 — 테스트 가능)."""
    opts: dict[str, Any] = {
        "locale": locale,
        "timezone_id": timezone_id,
        "viewport": {"width": viewport[0], "height": viewport[1]},
    }
    if user_agent:
        opts["user_agent"] = user_agent
    if storage_state:
        opts["storage_state"] = storage_state
    return opts


@asynccontextmanager
async def browser_context(**launch_kwargs) -> AsyncIterator[BrowserContext]:
    """Provide a managed Playwright browser context."""
    async with async_playwright() as p:
        browser: Browser = await p.chromium.launch(**launch_kwargs)
        context = await browser.new_context()
        try:
            yield context
        finally:
            await context.close()
            await browser.close()


@asynccontextmanager
async def stealth_context(
    headless: bool = True,
    block_resources: bool = True,
    context_options: Optional[dict[str, Any]] = None,
    **launch_kwargs,
) -> AsyncIterator[BrowserContext]:  # pragma: no cover - 실제 브라우저 필요
    """안티봇 대응 스텔스 컨텍스트(init script + 리소스 차단 + ko-KR 로케일)."""
    options = context_options or stealth_context_options()
    async with async_playwright() as p:
        browser: Browser = await p.chromium.launch(headless=headless, **launch_kwargs)
        context = await browser.new_context(**options)
        await context.add_init_script(STEALTH_INIT_SCRIPT)
        if block_resources:
            async def _route(route):
                if route.request.resource_type in _BLOCKED_RESOURCE_TYPES:
                    await route.abort()
                else:
                    await route.continue_()

            await context.route("**/*", _route)
        try:
            yield context
        finally:
            await context.close()
            await browser.close()


async def with_page(callback: Callable[[Page], Awaitable[None]], **launch_kwargs) -> None:
    """Utility to execute a callback within a temporary page."""
    async with browser_context(**launch_kwargs) as context:
        page = await context.new_page()
        await callback(page)
        await page.close()
