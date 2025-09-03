#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Playwright 기반: URL의 렌더링된(자바스크립트 실행 후) HTML을 가져와 prettify하여 .html로 저장

사용 예시:
    python testplay.py -u "https://www.uplusumobile.com/product/pric/pricDetail?seq=470&upPpnCd=U009&devKdCd=003" -o out.html

필수:
    pip install playwright beautifulsoup4 lxml
    playwright install
"""

import argparse
import asyncio
import datetime as dt
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright


def sanitize_filename(text: str, fallback: str = "output") -> str:
    text = re.sub(r"[^\w\-.]+", "_", text, flags=re.UNICODE)
    text = text.strip("._")
    return text or fallback


def guess_output_name(url: str) -> str:
    p = urlparse(url)
    host = sanitize_filename(p.netloc or "site")
    path = sanitize_filename((p.path or "/").strip("/").replace("/", "_") or "index")
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{host}-{path}-{ts}.html"


def extract_doctype(raw_html: str) -> str:
    m = re.search(r"(?is)<!DOCTYPE\s+[^>]+>", raw_html)
    return m.group(0).strip() if m else ""


def prettify_html(raw_html: str, parser: str = "lxml") -> str:
    soup = BeautifulSoup(raw_html, parser)
    pretty = soup.prettify()
    # prettify 과정에서 DOCTYPE이 빠질 수 있어 보존
    doc_in_raw = extract_doctype(raw_html)
    if doc_in_raw and "<!DOCTYPE" not in pretty[:200].upper():
        pretty = doc_in_raw + "\n" + pretty
    return pretty


def build_header_comment(url: str, note: str = "") -> str:
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    note = f"\n  Note: {note}" if note else ""
    return (
        "<!--\n"
        f"  Fetched-From: {url}\n"
        f"  Fetched-At:   {ts}\n"
        "  Status:       Rendered via Playwright"
        f"{note}\n"
        "  Scripts/CSS/리소스는 포함되지 않습니다.\n"
        "-->\n"
    )


async def fetch_rendered_html(url: str, wait_ms: int, timeout_ms: int, ua: str, locale: str, geolocation: str | None) -> str:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context_kwargs = {"user_agent": ua, "locale": locale}
        if geolocation:
            # geolocation 예시: "37.5665,126.9780"
            try:
                lat, lon = [float(x) for x in geolocation.split(",")]
                context_kwargs.update({"geolocation": {"latitude": lat, "longitude": lon}, "permissions": ["geolocation"]})
            except Exception:
                pass
        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()
        try:
            # networkidle: 네트워크 요청이 잠잠해질 때까지
            await page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            if wait_ms > 0:
                await page.wait_for_timeout(wait_ms)
            html = await page.content()
            return html
        finally:
            await context.close()
            await browser.close()


async def amain():
    ap = argparse.ArgumentParser(description="Fetch rendered HTML with Playwright and prettify to .html")
    ap.add_argument("-u", "--url", required=True, help="가져올 URL")
    ap.add_argument("-o", "--output", help="저장 파일명(.html). 기본: <host>-<path>-<ts>.html")
    ap.add_argument("-p", "--parser", default="lxml",
                    choices=["lxml", "html.parser", "html5lib"], help="BeautifulSoup 파서")
    ap.add_argument("--wait", type=int, default=300, help="로드 완료 후 추가 대기(ms)")
    ap.add_argument("--timeout", type=int, default=20000, help="페이지 로드 타임아웃(ms)")
    ap.add_argument("--ua", "--user-agent", dest="ua", default=(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ), help="User-Agent 문자열")
    ap.add_argument("--locale", default="ko-KR", help="브라우저 locale (기본: ko-KR)")
    ap.add_argument("--geo", "--geolocation", dest="geo", help="지오로케이션 'lat,lon' (옵션)")
    args = ap.parse_args()

    try:
        raw_html = await fetch_rendered_html(args.url, args.wait, args.timeout, args.ua, args.locale, args.geo)
    except Exception as e:
        print(f"[가져오기 실패] {e}", file=sys.stderr)
        sys.exit(2)

    pretty_html = prettify_html(raw_html, parser=args.parser)
    header = build_header_comment(args.url, note=f"Timeout={args.timeout}ms, ExtraWait={args.wait}ms")
    final_html = header + pretty_html

    out_path = Path(args.output or guess_output_name(args.url))
    if out_path.suffix.lower() != ".html":
        out_path = out_path.with_suffix(".html")
    out_path.write_text(final_html, encoding="utf-8", newline="\n")
    print(f"[완료] 저장: {out_path.resolve()}")


def main():
    asyncio.run(amain())


if __name__ == "__main__":
    main()
