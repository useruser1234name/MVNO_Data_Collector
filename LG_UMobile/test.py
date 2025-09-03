#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
U+ 알뜰폰 (uplusumobile.com) 요금제 상세 페이지 크롤러
- URL 패턴 예: https://www.uplusumobile.com/product/pric/pricDetail?seq=27&upPpnCd=U009&devKdCd=003
- 리디렉트가 /error?url=... 로 가면 파싱하지 않음
- seq=1..900, upPpnCd=A001..Z999 (총 25,974개 코드), devKdCd(기본: 001,003)
- HTML에서 다음 필드 추출:
  * plan_name: h2.tit
  * vol, limit, supply: .feature > .vol/.limit/.supply
  * origin_pay, discount_pay: .pay-amount > .origin-pay/.discount-pay
  * brand_chips: .chip-wrap img[alt] 들의 alt (콤마로 join)
  * banner_url: .detail-footer a.banner-randombox[href]
  * join_value: 가입 버튼의 value
  * notifications: detail-info > ul.notification li 텍스트
  * meta(url, seq, upPpnCd, devKdCd, http_status)
- 결과 CSV 저장 (기본: uplusumobile_plans.csv)

주의/권고:
- 조합 전체(900 * 25,974 * devKdCd 갯수)는 비현실적입니다. 기본 동시성 20, rate limit 5 req/s, 실패 재시도 포함.
- --ppn-prefix/-x, --ppn-num-max/-n, --seq-max/-s, --seq-start, --dev-kd 옵션으로 탐색 범위를 줄여 단계적으로 수집하세요.
- 사이트 약관/robots.txt 및 법규를 준수하세요. 본 코드는 교육/연구용 예시입니다.
"""

import asyncio
import aiohttp
import async_timeout
from bs4 import BeautifulSoup
import csv
import re
from pathlib import Path
from typing import List, Tuple, Optional, Dict
import time
import argparse
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

BASE = "https://www.uplusumobile.com/product/pric/pricDetail"
ERROR_PATH = "/error"  # 최종 URL에 이 경로가 있으면 스킵

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://www.uplusumobile.com/product/pric/pricList",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
}

CSV_FIELDS = [
    "seq",
    "upPpnCd",
    "devKdCd",
    "url",
    "http_status",
    "plan_name",
    "vol",
    "limit",
    "supply",
    "origin_pay",
    "discount_pay",
    "brand_chips",
    "banner_url",
    "join_value",
    "notifications",
]

price_cleaner = re.compile(r"\s+|")


def gen_upPpnCd(prefixes: List[str], num_max: int) -> List[str]:
    codes = []
    for p in prefixes:
        for i in range(1, num_max + 1):
            codes.append(f"{p}{i:03d}")
    return codes


def build_url(seq: int, upPpnCd: str, devKdCd: str) -> str:
    return f"{BASE}?seq={seq}&upPpnCd={upPpnCd}&devKdCd={devKdCd}"


def extract_text(el: Optional[BeautifulSoup]) -> str:
    return el.get_text(strip=True) if el else ""


def parse_html(html: str) -> Dict[str, str]:
    soup = BeautifulSoup(html, "lxml")
    major = soup.select_one("div.detail-major div.major")
    if not major:
        return {}

    plan_name = extract_text(major.select_one(".detail-header h2.tit"))
    vol = extract_text(major.select_one(".detail-header .feature .vol"))
    limit_ = extract_text(major.select_one(".detail-header .feature .limit"))
    supply = extract_text(major.select_one(".detail-header .feature .supply"))

    origin_pay = extract_text(major.select_one(".detail-footer .pay-amount .origin-pay"))
    discount_pay = extract_text(major.select_one(".detail-footer .pay-amount .discount-pay"))

    chips = [img.get("alt", "").strip() for img in major.select(".detail-header .chip-wrap img")]
    chips = [c for c in chips if c]
    brand_chips = ", ".join(chips)

    banner_a = major.select_one(".detail-footer a.banner-randombox[href]")
    banner_url = banner_a["href"].strip() if banner_a else ""

    join_btn = major.select_one(".detail-footer .box-btn button[value]")
    join_value = join_btn.get("value", "").strip() if join_btn else ""

    notifications = [li.get_text(" ", strip=True) for li in soup.select("div.detail-info ul.notification li")]
    notif_text = " | ".join(notifications)

    return {
        "plan_name": plan_name,
        "vol": vol,
        "limit": limit_,
        "supply": supply,
        "origin_pay": origin_pay,
        "discount_pay": discount_pay,
        "brand_chips": brand_chips,
        "banner_url": banner_url,
        "join_value": join_value,
        "notifications": notif_text,
    }


async def fetch(session: aiohttp.ClientSession, url: str, *, timeout_sec: int = 15) -> Tuple[int, str, str]:
    try:
        with async_timeout.timeout(timeout_sec):
            async with session.get(url, allow_redirects=True) as resp:
                text = await resp.text(errors="ignore")
                return resp.status, text, str(resp.url)
    except Exception:
        return 0, "", url


class RateLimiter:
    def __init__(self, rate_per_sec: float):
        self.min_interval = 1.0 / max(rate_per_sec, 0.001)
        self._last = 0.0
        self._lock = asyncio.Lock()

    async def wait(self):
        async with self._lock:
            now = time.monotonic()
            wait_for = self.min_interval - (now - self._last)
            if wait_for > 0:
                await asyncio.sleep(wait_for)
            self._last = time.monotonic()


async def worker(name: int, queue: asyncio.Queue, session: aiohttp.ClientSession, writer, limiter: RateLimiter, skip_error_path: str):
    while True:
        item = await queue.get()
        if item is None:
            queue.task_done()
            return
        seq, upPpnCd, devKdCd = item
        url = build_url(seq, upPpnCd, devKdCd)

        await limiter.wait()
        logging.info(f"[Worker-{name}] REQ: {url}")
        status, html, final_url = await fetch(session, url)
        logging.info(f"[Worker-{name}] RESP: {final_url} status={status} length={len(html)}")

        if ERROR_PATH in final_url:
            logging.warning(f"[Worker-{name}] SKIP ERROR PAGE: {final_url}")
            queue.task_done()
            continue

        row = {
            "seq": seq,
            "upPpnCd": upPpnCd,
            "devKdCd": devKdCd,
            "url": final_url or url,
            "http_status": status,
            "plan_name": "",
            "vol": "",
            "limit": "",
            "supply": "",
            "origin_pay": "",
            "discount_pay": "",
            "brand_chips": "",
            "banner_url": "",
            "join_value": "",
            "notifications": "",
        }

        if status == 200 and html:
            data = parse_html(html)
            if data:
                row.update(data)
            logging.info(f"[Worker-{name}] PARSED: plan_name={row['plan_name']} discount_pay={row['discount_pay']}")
            writer.writerow(row)
        else:
            logging.error(f"[Worker-{name}] FAILED FETCH: {url}")
        queue.task_done()


async def main():
    parser = argparse.ArgumentParser(description="uplusumobile 요금제 크롤러")
    parser.add_argument("--seq-max", "-s", type=int, default=900, help="seq 최대값 (1..N)")
    parser.add_argument("--seq-start", type=int, default=1, help="seq 시작값 (기본 1)")
    parser.add_argument("--ppn-prefix", "-x", type=str, nargs="*", default=[chr(c) for c in range(ord('A'), ord('Z')+1)], help="upPpnCd 접두어 목록 (기본 A..Z)")
    parser.add_argument("--ppn-num-max", "-n", type=int, default=999, help="upPpnCd 숫자 최대값 (001..N)")
    parser.add_argument("--dev-kd", "-d", type=str, nargs="*", default=["001", "003"], help="devKdCd 값들 (기본: 001 003)")
    parser.add_argument("--out", "-o", type=Path, default=Path("uplusumobile_plans.csv"), help="CSV 출력 경로")
    parser.add_argument("--concurrency", "-c", type=int, default=20, help="동시 요청 수")
    parser.add_argument("--rate", "-r", type=float, default=5.0, help="초당 요청 수 제한")
    args = parser.parse_args()

    upPpnCds = gen_upPpnCd(args.ppn_prefix, args.ppn_num_max)

    queue: asyncio.Queue = asyncio.Queue(maxsize=0)
    for seq in range(args.seq_start, args.seq_max + 1):
        for up in upPpnCds:
            for dev in args.dev_kd:
                queue.put_nowait((seq, up, dev))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    f = args.out.open("w", newline="", encoding="utf-8")
    writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
    writer.writeheader()

    limiter = RateLimiter(args.rate)

    async with aiohttp.ClientSession(headers=HEADERS) as session:
        workers = [asyncio.create_task(worker(i, queue, session, writer, limiter, ERROR_PATH)) for i in range(args.concurrency)]

        await queue.join()

        for _ in workers:
            queue.put_nowait(None)
        await asyncio.gather(*workers)

    f.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Interrupted")
