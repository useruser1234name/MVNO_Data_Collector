#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Siwol Mobile 요금제 페이지 스크레이퍼
--------------------------------------------------
1) 지정된 두 URL(LTE/5G)에서 class="card_rate_link" 의 href를 수집
2) https://siwolmobile.com/ + href 로 절대 URL 생성
3) siwol_plan_urls.csv 로 저장
4) 각 URL 페이지를 열어 전체 HTML을 파싱
5) HTML 내 모든 요소의 class 속성별 텍스트를 수집
6) 와이드 CSV: siwol_pages_by_class.csv (행=페이지, 열=클래스명)
7) 롱 CSV: siwol_pages_classes_long.csv (행=(url, class))
"""

import time
import re
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
import pandas as pd

BASE = "https://siwolmobile.com/"
SEED_URLS = [
    "https://siwolmobile.com/rate_plan.do?type=T002",  # LTE
    "https://siwolmobile.com/rate_plan.do?type=T005",  # 5G
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/129.0.0.0 Safari/537.36"
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

OUT_URLS_CSV = "siwol_plan_urls.csv"
OUT_WIDE_CSV = "siwol_pages_by_class.csv"
OUT_LONG_CSV = "siwol_pages_classes_long.csv"


def fetch(url, max_retries=3, timeout=20):
    for attempt in range(1, max_retries + 1):
        try:
            resp = SESSION.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            if attempt == max_retries:
                raise
            time.sleep(1.5 * attempt)


def squash_spaces(s: str) -> str:
    return re.sub(r'\s+', ' ', s).strip()


def extract_card_rate_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    links = []
    for a in soup.select(".card_rate_link[href]"):
        href = a.get("href", "").strip()
        if not href:
            continue
        abs_url = urljoin(base_url, href)
        links.append(abs_url)
    return list(dict.fromkeys(links))  # 중복 제거


def parse_classes_from_page(html: str) -> dict[str, list[str]]:
    soup = BeautifulSoup(html, "lxml")
    class_map = {}
    for el in soup.find_all(class_=True):
        classes = el.get("class")
        if not classes:
            continue
        text = el.get_text(separator=" ", strip=True)
        if not text:
            continue
        text = squash_spaces(text)
        for cls in classes:
            class_map.setdefault(cls, []).append(text)
    return class_map


def safe_join_texts(texts: list[str], sep=" | ", max_len=4000) -> str:
    out, curr_len = [], 0
    for t in texts:
        add = (sep if out else "") + t
        if curr_len + len(add) > max_len:
            break
        out.append(t)
        curr_len += len(add)
    return sep.join(out)


def main():
    # 1) 카드 링크 수집
    all_detail_urls = []
    for seed in SEED_URLS:
        html = fetch(seed)
        links = extract_card_rate_links(html, BASE)
        all_detail_urls.extend(links)
    all_detail_urls = list(dict.fromkeys(all_detail_urls))

    # 2) URL 저장
    pd.DataFrame({"url": all_detail_urls}).to_csv(
        OUT_URLS_CSV, index=False, encoding="utf-8-sig"
    )
    print(f"[저장 완료] {OUT_URLS_CSV} ({len(all_detail_urls)}건)")

    # 3) 상세 페이지 파싱
    all_classes, per_page_class_texts = set(), []
    for url in all_detail_urls:
        try:
            html = fetch(url)
            class_map = parse_classes_from_page(html)
        except Exception as e:
            print(f"[경고] 실패: {url} -> {e}")
            class_map = {"__url__": url, "__error__": str(e)}
        else:
            class_map["__url__"] = url
            all_classes.update(class_map.keys())
        per_page_class_texts.append(class_map)
        time.sleep(0.5)

    # 4) 와이드 CSV
    all_classes = sorted(c for c in all_classes if not c.startswith("__"))
    wide_rows = []
    for class_map in per_page_class_texts:
        row = {"url": class_map.get("__url__", "")}
        for cls in all_classes:
            texts = class_map.get(cls, [])
            row[cls] = safe_join_texts(texts) if isinstance(texts, list) else ""
        wide_rows.append(row)
    pd.DataFrame(wide_rows).to_csv(OUT_WIDE_CSV, index=False, encoding="utf-8-sig")
    print(f"[저장 완료] {OUT_WIDE_CSV}")

    # 5) 롱 CSV
    long_records = []
    for class_map in per_page_class_texts:
        url = class_map.get("__url__", "")
        if "__error__" in class_map:
            long_records.append({
                "url": url,
                "class_name": "__error__",
                "text_joined": class_map["__error__"],
                "count": 0
            })
            continue
        for cls, texts in class_map.items():
            if cls.startswith("__"):
                continue
            if not texts:
                continue
            if not isinstance(texts, list):
                texts = [str(texts)]
            long_records.append({
                "url": url,
                "class_name": cls,
                "text_joined": safe_join_texts(texts),
                "count": len(texts)
            })
    pd.DataFrame(long_records).to_csv(OUT_LONG_CSV, index=False, encoding="utf-8-sig")
    print(f"[저장 완료] {OUT_LONG_CSV}")


if __name__ == "__main__":
    main()
