#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
fetch_html_pretty.py
- URL의 전체 HTML을 가져와 보기 좋게 정리(prettify)한 뒤 .html 파일로 저장
- 기본 파서는 lxml (설치 필요). --parser로 변경 가능: lxml | html.parser | html5lib
- 예시:
    python fetch_html_pretty.py --url "https://example.com"
    python fetch_html_pretty.py -u "https://example.com" -o out.html
"""

import argparse
import datetime as dt
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


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


def fetch_html(url: str, insecure: bool = False, timeout: int = 20) -> requests.Response:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko,en;q=0.9",
    }
    resp = requests.get(url, headers=headers, timeout=timeout, verify=not insecure)
    resp.raise_for_status()
    # 인코딩 보정: 서버가 ISO-8859-1로 주는 경우 추정값 사용
    if not resp.encoding or resp.encoding.lower() in ("iso-8859-1", "us-ascii"):
        resp.encoding = resp.apparent_encoding or "utf-8"
    return resp


def prettify_html(raw_html: str, parser: str = "lxml") -> str:
    soup = BeautifulSoup(raw_html, parser)
    pretty = soup.prettify()
    # prettify 과정에서 DOCTYPE이 사라지는 경우가 있어 보존 처리
    doc_in_raw = extract_doctype(raw_html)
    if doc_in_raw and "<!DOCTYPE" not in pretty[:200].upper():
        pretty = doc_in_raw + "\n" + pretty
    return pretty


def build_header_comment(url: str, status_code: int) -> str:
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return (
        "<!--\n"
        f"  Fetched-From: {url}\n"
        f"  Fetched-At:   {ts}\n"
        f"  Status-Code:  {status_code}\n"
        "  Note: This file is the prettified HTML. Scripts/CSS/리소스는 포함되지 않습니다.\n"
        "-->\n"
    )


def main():
    ap = argparse.ArgumentParser(description="Fetch and prettify HTML into a .html file")
    ap.add_argument("-u", "--url", required=True, help="크롤링할 URL")
    ap.add_argument(
        "-o", "--output", help="저장할 파일명 (.html). 기본: <host>-<path>-<timestamp>.html"
    )
    ap.add_argument(
        "-p",
        "--parser",
        default="lxml",
        choices=["lxml", "html.parser", "html5lib"],
        help="BeautifulSoup 파서 선택 (기본: lxml)",
    )
    ap.add_argument(
        "--insecure",
        action="store_true",
        help="SSL 인증서 검증 비활성화 (self-signed 등 문제 시)",
    )
    args = ap.parse_args()

    try:
        resp = fetch_html(args.url, insecure=args.insecure)
    except requests.exceptions.SSLError as e:
        print(f"[SSL 오류] {e}\n--insecure 옵션을 시도해 보세요.", file=sys.stderr)
        sys.exit(2)
    except requests.exceptions.HTTPError as e:
        print(f"[HTTP 오류] {e}", file=sys.stderr)
        sys.exit(2)
    except requests.exceptions.RequestException as e:
        print(f"[요청 실패] {e}", file=sys.stderr)
        sys.exit(2)

    raw_html = resp.text
    pretty_html = prettify_html(raw_html, parser=args.parser)

    header = build_header_comment(args.url, resp.status_code)
    final_html = header + pretty_html

    out_path = Path(args.output or guess_output_name(args.url))
    # 확장자 보정
    if out_path.suffix.lower() != ".html":
        out_path = out_path.with_suffix(".html")

    out_path.write_text(final_html, encoding="utf-8", newline="\n")
    print(f"[완료] 저장: {out_path.resolve()}")


if __name__ == "__main__":
    main()
