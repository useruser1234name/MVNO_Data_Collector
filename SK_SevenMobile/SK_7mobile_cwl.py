import re
import sys
import time
import json
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from itertools import chain
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ======================
# 설정
# ======================
INPUT_FILES = [
    "callingPlan_PHONE_PROD_LTE_TYPE_ALL_6.txt",   # 134개
    "callingPlan_USIM_PROD_USIM_TYPE_ALL_6.txt",   # 69개
]
OUT_CSV = "sk7_detail_crawl.csv"
OUT_NDJSON = None
REQUEST_INTERVAL_SEC = 0.2   # 매너 타임

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

# 재시도 세션
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

def load_urls(*files) -> list[str]:
    urls = []
    for f in files:
        p = Path(f)
        if not p.exists():
            print(f"⚠️ 파일 없음: {f}")
            continue
        with p.open("r", encoding="utf-8") as fh:
            for line in fh:
                u = line.strip()
                if u:
                    urls.append(u)
    # 중복 제거(정렬은 prodCd 기준으로)
    urls = list(dict.fromkeys(urls))  # 순서 유지 dedup
    return urls

def parse_money(txt: str | None) -> int | None:
    """예: '24,200원' -> 24200 (없으면 None)"""
    if not txt:
        return None
    m = re.findall(r"\d+", txt.replace(",", ""))
    return int("".join(m)) if m else None

def get_text(node) -> str | None:
    return node.get_text(strip=True) if node else None

def classes_text(tag) -> str:
    """
    BeautifulSoup tag의 class 속성을 'a b c' 형태 문자열로 안전하게 변환.
    class가 없거나 None이면 '' 반환
    """
    if not tag:
        return ""
    cls = tag.get("class")
    if not cls:
        return ""
    return " ".join(map(str, cls))

def icons_classes_text(container) -> str:
    """
    container 내부의 <i> 태그들의 class들을 전부 평탄화해 'a b c' 문자열로.
    """
    class_lists = (i.get("class") or [] for i in container.select("i"))
    flat = chain.from_iterable(class_lists)  # 리스트들의 제너레이터 → 1차원으로 평탄화
    return " ".join(map(str, flat))


def extract_prodcd_from_url(url: str) -> str | None:
    try:
        qs = parse_qs(urlparse(url).query)
        vals = qs.get("prodCd")
        return vals[0] if vals else None
    except Exception:
        return None

def fetch_soup(session: requests.Session, url: str) -> BeautifulSoup:
    r = session.get(url, timeout=20)
    # 인코딩 보정
    if not r.encoding or r.encoding.lower() == "iso-8859-1":
        r.encoding = "utf-8"
    r.raise_for_status()
    return BeautifulSoup(r.text, "lxml")

def parse_detail_page(soup: BeautifulSoup, url: str) -> dict:
    # hidden inputs
    refCode = soup.select_one('input#refCode')
    searchCallPlanType = soup.select_one('input#searchCallPlanType')
    searchOrderby = soup.select_one('input#searchOrderby')
    refCode_v = refCode.get("value").strip() if refCode and refCode.get("value") else None
    callType_v = searchCallPlanType.get("value").strip() if searchCallPlanType and searchCallPlanType.get("value") else None
    orderby_v = searchOrderby.get("value").strip() if searchOrderby and searchOrderby.get("value") else None

    # 제목
    title = get_text(soup.select_one("h2.title"))

    # badge
    badges = [get_text(x) for x in soup.select(".badge-wp span") if get_text(x)]

    # plan-info: sr-only 라벨 기반 파싱 (라벨이 가장 견고)
    data_txt = voice_txt = sms_txt = None
    for li in soup.select("div.plan-info li"):
        label = get_text(li.select_one("span.sr-only"))  # 예: 데이터 제공량 / 음성 제공량 / 문자 제공량
        value = get_text(li.select_one("p"))
        if not label:
            # 아이콘 클래스 기반 보조 파싱
            # 아이콘 클래스 기반 보조 파싱 (안전한 평탄화)
            cls = (classes_text(li) + " " + icons_classes_text(li)).strip()
            if "icon-data" in cls:
                data_txt = value
            elif "icon-call" in cls:
                voice_txt = value
            elif "icon-sms" in cls:
                sms_txt = value

            continue

        if "데이터" in label:
            data_txt = value
        elif "음성" in label:
            voice_txt = value
        elif "문자" in label:
            sms_txt = value

    # 가격: 기본료 / 프로모션 할인 후 기본료
    price_base = price_promo = None
    item1 = soup.select_one(".price-lst .item1")
    if item1:
        price_base = parse_money(get_text(item1.select_one("p b")) or get_text(item1))
    item2 = soup.select_one(".price-lst .item2")
    if item2:
        price_promo = parse_money(get_text(item2.select_one("p b")) or get_text(item2))

    prodCd = extract_prodcd_from_url(url)

    return {
        "prodCd": prodCd,
        "refCode": refCode_v,
        "searchCallPlanType": callType_v,
        "searchOrderby": orderby_v,
        "title": title,
        "badges": "|".join(badges) if badges else None,
        "data": data_txt,
        "voice": voice_txt,
        "sms": sms_txt,
        "price_base": price_base,
        "price_promo": price_promo,
        "url": url,
    }

def write_outputs(rows: list[dict], csv_path: str, ndjson_path: str):
    # CSV
    import csv
    fieldnames = [
        "prodCd","refCode","searchCallPlanType","searchOrderby",
        "title","badges","data","voice","sms",
        "price_base","price_promo","url"
    ]
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fieldnames})

    # NDJSON
    with open(ndjson_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

def main():
    urls = load_urls(*INPUT_FILES)
    print(f"[입력 URL] 총 {len(urls)}개 (중복 제거 후)")

    s = build_session()
    rows = []
    bad = []
    for i, url in enumerate(urls, 1):
        try:
            soup = fetch_soup(s, url)
            row = parse_detail_page(soup, url)
            rows.append(row)
            if i % 20 == 0:
                print(f"  - 진행 {i}/{len(urls)} … 예: {row['prodCd']} / {row['title']}")
        except requests.RequestException as e:
            bad.append((url, f"HTTP {e}"))
            print(f"✗ HTTP 오류: {url} -> {e}")
        except Exception as e:
            bad.append((url, f"PARSE {e}"))
            print(f"✗ 파싱 오류: {url} -> {e}")
        time.sleep(REQUEST_INTERVAL_SEC)

    write_outputs(rows, OUT_CSV, OUT_NDJSON)

    # 요약
    print("\n[요약]")
    print(f"- 성공: {len(rows)}")
    print(f"- 실패: {len(bad)}")
    if bad:
        print("  일부 실패 샘플:")
        for u, why in bad[:5]:
            print("   ", why, u)
        # 실패 목록 저장
        with open("sk7_detail_failed.txt", "w", encoding="utf-8") as f:
            for u, why in bad:
                f.write(f"{why}\t{u}\n")

if __name__ == "__main__":
    # 파일명을 커맨드라인에서 넘기고 싶으면: python script.py f1.txt f2.txt
    if len(sys.argv) > 1:
        INPUT_FILES = sys.argv[1:]
    main()
