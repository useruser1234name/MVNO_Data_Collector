import re
import sys
import time
import csv
from collections import Counter
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ======================
# 설정
# ======================
LIST_URLS = [
    # PHONE / LTE
    "https://www.sk7mobile.com/prod/data/callingPlanList.do?refCode=PHONE&searchCallPlanType=PROD_LTE_TYPE_ALL&searchOrderby=6",
    # USIM
    "https://www.sk7mobile.com/prod/data/callingPlanList.do?refCode=USIM&searchCallPlanType=PROD_USIM_TYPE_ALL&searchOrderby=6",
]
VIEW_BASE = "https://www.sk7mobile.com/prod/data/callingPlanView.do"
OUT_CSV = "sk7_container_dump.csv"
REQUEST_INTERVAL_SEC = 0.5  # 매너 타임

# 헤더(필수)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.sk7mobile.com/",
    "Connection": "keep-alive",
}

def build_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    retries = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST"),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s

def fetch_soup(session: requests.Session, url: str) -> BeautifulSoup:
    r = session.get(url, timeout=20)
    if not r.encoding or r.encoding.lower() == "iso-8859-1":
        r.encoding = "utf-8"
    r.raise_for_status()
    return BeautifulSoup(r.text, "lxml")

def parse_total(soup: BeautifulSoup) -> int | None:
    node = soup.select_one("p.total span")
    if not node:
        return None
    m = re.search(r"\d+", node.get_text(strip=True))
    return int(m.group()) if m else None

# PD/PC + 영숫자 모두 허용
PROD_RE = re.compile(r"""fnSearchView\(['"](?P<prod>(?:PD|PC)[A-Za-z0-9]+)['"]\)""")

def extract_prod_codes(soup: BeautifulSoup) -> list[str]:
    found = set()
    for tag in soup.find_all(attrs={"onclick": True}):
        onclick = tag.get("onclick") or ""
        m = PROD_RE.search(onclick)
        if m:
            found.add(m.group("prod"))
    return sorted(found)

def get_view_params_from_page_or_url(soup: BeautifulSoup, list_url: str) -> dict:
    """
    상세 URL 파라미터(refCode, searchCallPlanType)를
    1) 페이지 hidden input에서 먼저 추출, 없으면
    2) 리스트 URL 쿼리에서 복구
    """
    ref = soup.select_one("input#refCode")
    typ = soup.select_one("input#searchCallPlanType")
    refCode = (ref.get("value").strip() if ref and ref.get("value") else None)
    callType = (typ.get("value").strip() if typ and typ.get("value") else None)

    if not (refCode and callType):
        qs = parse_qs(urlparse(list_url).query)
        refCode = refCode or qs.get("refCode", [None])[0]
        callType = callType or qs.get("searchCallPlanType", [None])[0]

    return {
        "refCode": refCode or "USIM",
        "searchCallPlanType": callType or "PROD_USIM_TYPE_ALL",
    }

def make_view_url(base_params: dict, prod_cd: str) -> str:
    qs = dict(base_params)
    qs["prodCd"] = prod_cd
    return f"{VIEW_BASE}?{urlencode(qs)}"

def extract_title(soup: BeautifulSoup) -> str | None:
    node = soup.select_one("h2.title")
    return node.get_text(strip=True) if node else None

def extract_hidden_values(soup: BeautifulSoup) -> tuple[str | None, str | None, str | None]:
    refCode = soup.select_one('input#refCode')
    callType = soup.select_one('input#searchCallPlanType')
    orderby = soup.select_one('input#searchOrderby')
    rv = refCode.get("value").strip() if refCode and refCode.get("value") else None
    cv = callType.get("value").strip() if callType and callType.get("value") else None
    ov = orderby.get("value").strip() if orderby and orderby.get("value") else None
    return rv, cv, ov

def crawl_list(session: requests.Session, list_url: str) -> tuple[dict, list[str]]:
    soup = fetch_soup(session, list_url)
    total = parse_total(soup)
    prod_codes = extract_prod_codes(soup)
    base_params = get_view_params_from_page_or_url(soup, list_url)
    detail_urls = [make_view_url(base_params, code) for code in prod_codes]
    meta = {
        "list_url": list_url,
        "list_total": total,
        "list_refCode": base_params["refCode"],
        "list_callType": base_params["searchCallPlanType"],
        "prefix_dist": dict(Counter(c[:2] for c in prod_codes)),
    }
    return meta, detail_urls

def prodcd_from_url(url: str) -> str | None:
    try:
        return (parse_qs(urlparse(url).query).get("prodCd") or [None])[0]
    except Exception:
        return None

def crawl_detail_container(session: requests.Session, detail_url: str) -> dict:
    soup = fetch_soup(session, detail_url)
    cont = soup.select_one("div.container")
    container_html = str(cont) if cont else None
    title = extract_title(soup)
    refCode_v, callType_v, orderby_v = extract_hidden_values(soup)
    return {
        "url": detail_url,
        "prodCd": prodcd_from_url(detail_url),
        "detail_refCode": refCode_v,
        "detail_callType": callType_v,
        "detail_orderby": orderby_v,
        "title": title,
        "container_html": container_html,
    }

def main():
    s = build_session()

    # 1) 두 개 리스트를 순차 수집하여 상세 URL 생성
    all_detail_urls = []
    list_metas = []
    for lu in LIST_URLS:
        meta, detail_urls = crawl_list(s, lu)
        list_metas.append(meta)
        all_detail_urls.extend(detail_urls)
        print(f"[리스트] {lu}")
        print(f"  - 표기 총 건수: {meta['list_total']}")
        print(f"  - 추출 prodCd 수: {len(detail_urls)}")
        print(f"  - 접두어 분포: {meta['prefix_dist']}")
        time.sleep(REQUEST_INTERVAL_SEC)

    # 2) 중복 제거(같은 prodCd가 두 리스트에 중복될 수 있음)
    dedup = {}
    for u in all_detail_urls:
        p = prodcd_from_url(u)
        if p and p not in dedup:
            dedup[p] = u
    tasks = list(dedup.items())  # (prodCd, url)

    print(f"\n[상세 대상] 총 {len(tasks)}개 (중복 제거 후)")
    if tasks:
        sample_urls = [u for _, u in tasks[:5]]
        print("[예시 5개]")
        for u in sample_urls:
            print(" ", u)

    # 3) 상세 페이지에서 container 수집 → CSV 저장
    rows = []
    bad = []
    for i, (prodCd, url) in enumerate(tasks, 1):
        try:
            row = crawl_detail_container(s, url)
            rows.append(row)
            if i % 20 == 0:
                print(f"  - 진행 {i}/{len(tasks)} … 예: {row.get('prodCd')} / {row.get('title')}")
        except requests.RequestException as e:
            bad.append((url, f"HTTP {e}"))
            print(f"✗ HTTP 오류: {url} -> {e}")
        except Exception as e:
            bad.append((url, f"PARSE {e}"))
            print(f"✗ 파싱 오류: {url} -> {e}")
        time.sleep(REQUEST_INTERVAL_SEC)

    # CSV 저장 (Excel 친화: utf-8-sig)
    fieldnames = [
        "prodCd", "url",
        "detail_refCode", "detail_callType", "detail_orderby",
        "title",
        "container_html",
    ]
    with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fieldnames})

    # 실패 목록 파일
    if bad:
        with open("sk7_container_failed.txt", "w", encoding="utf-8") as f:
            for u, why in bad:
                f.write(f"{why}\t{u}\n")

    # 요약
    print("\n[요약]")
    print(f"- 리스트 수집: {len(LIST_URLS)}개")
    for meta in list_metas:
        print(f"  · {meta['list_url']} -> 표기 {meta['list_total']}, 추출 {sum(meta['prefix_dist'].values())}, 분포 {meta['prefix_dist']}")
    print(f"- 상세 성공: {len(rows)}")
    print(f"- 상세 실패: {len(bad)}")
    print(f"- CSV 저장: {OUT_CSV}")

if __name__ == "__main__":
    try:
        main()
    except requests.RequestException as e:
        print(f"HTTP 오류: {e}", file=sys.stderr)
        sys.exit(1)
