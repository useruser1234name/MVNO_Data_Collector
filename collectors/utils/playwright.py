"""Shared Playwright helpers used by collectors."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Awaitable, Callable

from playwright.async_api import async_playwright, Browser, BrowserContext, Page


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


async def with_page(callback: Callable[[Page], Awaitable[None]], **launch_kwargs) -> None:
    """Utility to execute a callback within a temporary page."""
    async with browser_context(**launch_kwargs) as context:
        page = await context.new_page()
        await callback(page)
        await page.close()
