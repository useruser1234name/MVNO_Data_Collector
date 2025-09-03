#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
U+ 알뜰폰 (uplusumobile.com) 요금제 크롤러 - Playwright 버전
"""

import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import csv
from pathlib import Path
import argparse
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

CSV_FIELDS = [
    "seq", "upPpnCd", "devKdCd", "url", "plan_name", "vol", "limit", "supply",
    "origin_pay", "discount_pay", "brand_chips", "banner_url", "join_value", "notifications"
]

BASE = "https://www.uplusumobile.com/product/pric/pricDetail"
ERROR_PATH = "/error"


def build_url(seq, upPpnCd, devKdCd):
    return f"{BASE}?seq={seq}&upPpnCd={upPpnCd}&devKdCd={devKdCd}"


def extract_text(el):
    return el.get_text(strip=True) if el else ""


def parse_html(html):
    soup = BeautifulSoup(html, "lxml")
    major = soup.select_one("div.detail-major div.major")
    if not major:
        return {}

    plan_name = extract_text(major.select_one(".detail-header h2.tit"))
    vol = extract_text(major.select_one(".feature .vol"))
    limit_ = extract_text(major.select_one(".feature .limit"))
    supply = extract_text(major.select_one(".feature .supply"))

    origin_pay = extract_text(major.select_one(".pay-amount .origin-pay"))
    discount_pay = extract_text(major.select_one(".pay-amount .discount-pay"))

    chips = [img.get("alt", "").strip() for img in major.select(".chip-wrap img") if img.get("alt")]
    brand_chips = ", ".join(chips)

    banner_a = major.select_one(".detail-footer a.banner-randombox[href]")
    banner_url = banner_a["href"].strip() if banner_a else ""

    join_btn = major.select_one(".detail-footer .box-btn button[value]")
    join_value = join_btn["value"].strip() if join_btn else ""

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


async def fetch_page(playwright, url, semaphore):
    async with semaphore:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto(url, timeout=20000)
            final_url = page.url
            if ERROR_PATH in final_url:
                logging.warning(f"SKIP ERROR PAGE: {url}")
                return None
            html = await page.content()
            data = parse_html(html)
            return final_url, data
        except Exception as e:
            logging.error(f"FAILED FETCH: {url} err={e}")
            return None
        finally:
            await browser.close()


async def main():
    parser = argparse.ArgumentParser(description="uplusumobile 크롤러 (Playwright)")
    parser.add_argument("--seq-start", type=int, default=1)
    parser.add_argument("--seq-max", type=int, default=5)
    parser.add_argument("--ppn-prefix", "-x", type=str, nargs="*", default=["U"])
    parser.add_argument("--ppn-num-max", "-n", type=int, default=10)
    parser.add_argument("--dev-kd", "-d", type=str, nargs="*", default=["001", "003"])
    parser.add_argument("--out", "-o", type=Path, default=Path("uplus_playwright.csv"))
    parser.add_argument("--concurrency", "-c", type=int, default=3, help="동시 브라우저 개수")
    args = parser.parse_args()

    upPpnCds = [f"{p}{i:03d}" for p in args.ppn_prefix for i in range(1, args.ppn_num_max + 1)]
    urls = [(seq, up, dev, build_url(seq, up, dev))
            for seq in range(args.seq_start, args.seq_max + 1)
            for up in upPpnCds
            for dev in args.dev_kd]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    f = args.out.open("w", newline="", encoding="utf-8")
    writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
    writer.writeheader()

    semaphore = asyncio.Semaphore(args.concurrency)

    async with async_playwright() as pw:
        tasks = [fetch_page(pw, url, semaphore) for seq, up, dev, url in urls]
        for (seq, up, dev, url), task in zip(urls, asyncio.as_completed(tasks)):
            result = await task
            if result:
                final_url, data = result
                row = {"seq": seq, "upPpnCd": up, "devKdCd": dev, "url": final_url}
                row.update(data)
                writer.writerow(row)

    f.close()
    logging.info(f"Done. Saved to {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
