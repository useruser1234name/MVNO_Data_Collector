#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Selenium 기반: URL의 렌더링된(자바스크립트 실행 후) HTML을 가져와 prettify하여 .html로 저장
사용 예시:
    python testsel.py -u "https://www.uplusumobile.com/product/pric/pricDetail?seq=470&upPpnCd=U009&devKdCd=003" -o out.html
필수:
    pip install selenium beautifulsoup4 lxml
    (Selenium 4.6+ 는 드라이버 자동관리 지원; 크롬 설치 권장)
"""

import argparse
import datetime as dt
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.support.ui import WebDriverWait


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
    # prettify 과정에서 DOCTYPE이 사라지는 경우 보존
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
        "  Status:       Rendered via Selenium"
        f"{note}\n"
        "  Scripts/CSS/리소스는 포함되지 않습니다.\n"
        "-->\n"
    )


def main():
    ap = argparse.ArgumentParser(description="Fetch rendered HTML with Selenium and prettify to .html")
    ap.add_argument("-u", "--url", required=True, help="가져올 URL")
    ap.add_argument("-o", "--output", help="저장 파일명(.html). 기본: <host>-<path>-<ts>.html")
    ap.add_argument("-p", "--parser", default="lxml",
                    choices=["lxml", "html.parser", "html5lib"], help="BeautifulSoup 파서")
    ap.add_argument("--headful", action="store_true", help="브라우저 창 표시(기본은 headless)")
    ap.add_argument("--wait", type=float, default=1.0, help="로드 완료 후 추가 대기(sec)")
    ap.add_argument("--timeout", type=int, default=25, help="페이지 로드 타임아웃(sec)")
    ap.add_argument("--ua", "--user-agent", dest="ua", default=(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ), help="User-Agent 문자열")
    args = ap.parse_args()

    # 브라우저 옵션
    try:
        opts = ChromeOptions()
        if not args.headful:
            opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--no-sandbox")
        opts.add_argument(f"--user-agent={args.ua}")
        opts.add_argument("--lang=ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7")

        driver = webdriver.Chrome(options=opts)  # Selenium 4.6+면 드라이버 자동관리
        driver.set_page_load_timeout(args.timeout)
    except Exception as e:
        print(f"[드라이버 초기화 실패] {e}", file=sys.stderr)
        sys.exit(2)

    try:
        driver.get(args.url)
        # DOM 로딩 대기
        WebDriverWait(driver, args.timeout).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        if args.wait > 0:
            time.sleep(args.wait)

        # 렌더링된 HTML
        raw_html = driver.execute_script("return document.documentElement.outerHTML;")
        pretty_html = prettify_html(raw_html, parser=args.parser)

        header = build_header_comment(args.url, note=f"Timeout={args.timeout}s, ExtraWait={args.wait}s")
        final_html = header + pretty_html

        out_path = Path(args.output or guess_output_name(args.url))
        if out_path.suffix.lower() != ".html":
            out_path = out_path.with_suffix(".html")
        out_path.write_text(final_html, encoding="utf-8", newline="\n")
        print(f"[완료] 저장: {out_path.resolve()}")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
