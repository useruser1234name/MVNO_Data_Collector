# uplusumobile_pricDetail_scrape.py
import re
import csv
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 입력: 이전 단계에서 만든 URL 목록 CSV(기본) 또는 txt(라인별 URL)
IN_FILE = "uplusumobile_pricDetail_urls.csv"
OUT_CSV = "uplusumobile_pricDetail_data.csv"
REQUEST_INTERVAL_SEC = 0.5  # 매너 타임

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.uplusumobile.com/",
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
    r = session.get(url, timeout=25)
    if not r.encoding or r.encoding.lower() == "iso-8859-1":
        r.encoding = "utf-8"
    r.raise_for_status()
    return BeautifulSoup(r.text, "lxml")

def parse_money(txt: str | None) -> int | None:
    if not txt:
        return None
    # "38,200원", "46,600 원" 등 → 38200, 46600
    m = re.findall(r"\d+", txt.replace(",", ""))
    return int("".join(m)) if m else None

def get_text(node) -> str | None:
    return node.get_text(strip=True) if node else None

def clean_spaces(s: str | None) -> str | None:
    if s is None:
        return None
    return re.sub(r"\s+", " ", s).strip()

def get_input_value(soup: BeautifulSoup, css: str) -> str | None:
    """hidden input 등에서 value 속성 추출"""
    el = soup.select_one(css)
    return el.get("value", "").strip() if el and el.has_attr("value") else None

def extract_params_from_url(url: str) -> dict:
    qs = parse_qs(urlparse(url).query)
    return {
        "seq": (qs.get("seq") or [None])[0],
        "upPpnCd": (qs.get("upPpnCd") or [None])[0],
        "devKdCd": (qs.get("devKdCd") or [None])[0],
    }

# ------------ Mbps 추출 유틸 ------------
def _direct_text(el) -> str:
    """자식 섹션/툴팁 같은 중첩 노드는 빼고, li 자신의 텍스트만."""
    if not el:
        return ""
    return "".join(el.find_all(string=True, recursive=False)).strip()

def _norm(s: str | None) -> str | None:
    if not s:
        return None
    return re.sub(r"\s+", " ", s).strip()

def extract_speed_toplist(soup: BeautifulSoup) -> str | None:
    """
    상단 안내 리스트(ul.notification.free)에서 'Mbps'가 들어간 한 줄만 추출.
    예) '최대 5Mbps 속도로 데이터 무제한 이용'
    """
    for li in soup.select("div.detail-info ul.notification.free > li"):
        txt = _direct_text(li)  # 내부 tooltip 텍스트 제외
        if re.search(r"(?i)\bmbps\b", txt):
            return _norm(txt)
    # fallback: detail-info 영역 전체에서 첫 번째 'Mbps' 문장
    for li in soup.select("div.detail-info li"):
        txt = _direct_text(li)
        if re.search(r"(?i)\bmbps\b", txt):
            return _norm(txt)
    return None

def extract_speed_from_data_guide(soup: BeautifulSoup) -> str | None:
    """
    '데이터 이용 안내' 섹션에서 'Mbps' 포함 문장(여러 개면 |로 합침)
    예) '월 기본 제공량 소진 시, 최대 5Mbps 속도로 데이터를 계속 사용…'
    """
    # 1) '데이터 이용 안내' 헤더 찾기 (h2 텍스트 매칭)
    h2 = None
    for h in soup.select("h2"):
        if "데이터 이용 안내" in h.get_text(strip=True):
            h2 = h
            break
    if not h2:
        return None

    # 2) 본문 컨테이너 추정
    cont = h2.find_next(class_=re.compile(r"(?:plan-detail-conts|acc-conts)"))
    if not cont:
        # 구조가 살짝 다를 경우 섹션/형제 범위에서 탐색
        sec = h2.find_parent("section")
        cont = sec or h2

    # 3) 해당 섹션 내에서 'Mbps' 포함 문장 수집
    hits = []
    for li in cont.select("li"):
        txt = " ".join(li.stripped_strings)
        if re.search(r"(?i)\bmbps\b", txt):
            hits.append(_norm(txt))

    if hits:
        uniq = list(dict.fromkeys(hits))  # 중복 제거
        return " | ".join(uniq)
    return None

def parse_detail_speed_bits(soup: BeautifulSoup) -> dict:
    return {
        "speed_toplist": extract_speed_toplist(soup),
        "speed_data_guide": extract_speed_from_data_guide(soup),
    }

# ------------ 상세 페이지 파서 ------------
def parse_detail_page(soup: BeautifulSoup, url: str) -> dict:
    # URL 파라미터(백업용)
    url_params = extract_params_from_url(url)

    # hidden inputs (상세 페이지에 거의 항상 존재) - value로 보정
    seq = get_input_value(soup, "input#seq") or url_params["seq"]
    ctgrId = get_input_value(soup, "input#ctgrId")

    # 가입 폼 hidden
    frm = soup.select_one("form#onsaleJoinFrm")
    hpPpnSeq = frm.select_one("#hpPpnSeq")["value"].strip() if frm and frm.select_one("#hpPpnSeq") else None
    hpPpnCd  = frm.select_one("#hpPpnCd")["value"].strip() if frm and frm.select_one("#hpPpnCd") else None
    upPpnCd  = (frm.select_one("#upPpnCd")["value"].strip() if frm and frm.select_one("#upPpnCd") else None) or url_params["upPpnCd"]
    sbscTypCd2 = frm.select_one("#sbscTypCd2")["value"].strip() if frm and frm.select_one("#sbscTypCd2") else None
    sbscTypCd3 = frm.select_one("#sbscTypCd3")["value"].strip() if frm and frm.select_one("#sbscTypCd3") else None
    feeName  = frm.select_one("#feeName")["value"].strip() if frm and frm.select_one("#feeName") else None
    feeType  = frm.select_one("#feeType")["value"].strip() if frm and frm.select_one("#feeType") else None

    # 타이틀
    title = clean_spaces(get_text(soup.select_one(".detail-header h2.tit")) or feeName)

    # 칩/뱃지 (텍스트, 이미지 alt 모두 수집)
    chips = []
    chip_wrap = soup.select_one(".detail-header .chip-wrap")
    if chip_wrap:
        # span.chip 텍스트
        for n in chip_wrap.select(".chip"):
            t = get_text(n)
            if t:
                chips.append(t)
        # 이미지 alt
        for img in chip_wrap.select("img[alt]"):
            alt = img.get("alt", "").strip()
            if alt:
                chips.append(alt)
    chips = "|".join(dict.fromkeys([c for c in chips if c])) or None  # 중복 제거, |로 합침

    # 상단 제공 정보 (데이터/통화/문자 등 표시)
    feature_vol = clean_spaces(get_text(soup.select_one(".detail-header .feature .vol")))
    feature_limit = clean_spaces(get_text(soup.select_one(".detail-header .feature .limit")))
    feature_supply = clean_spaces(get_text(soup.select_one(".detail-header .feature .supply")))

    # 요금(정가/할인가)
    origin_pay_txt = get_text(soup.select_one(".detail-footer .pay-amount .origin-pay"))
    discount_pay_txt = get_text(soup.select_one(".detail-footer .pay-amount .discount-pay"))
    price_origin = parse_money(origin_pay_txt)
    price_discount = parse_money(discount_pay_txt)

    # devKdCd: URL 파라미터 또는 페이지 내부에서 유추 (없으면 None)
    devKdCd = url_params["devKdCd"]

    # Mbps 문구 추출
    speed_bits = parse_detail_speed_bits(soup)

    row = {
        "site": "uplusumobile",
        "seq": seq,
        "ctgrId": ctgrId,
        "hpPpnSeq": hpPpnSeq,
        "hpPpnCd": hpPpnCd,
        "upPpnCd": upPpnCd,
        "devKdCd": devKdCd,
        "sbscTypCd2": sbscTypCd2,
        "sbscTypCd3": sbscTypCd3,
        "feeName": feeName,
        "feeType": feeType,
        "title": title,
        "feature_vol": feature_vol,
        "feature_limit": feature_limit,
        "feature_supply": feature_supply,
        "price_origin": price_origin,
        "price_discount": price_discount,
        "chips": chips,
        "detail_url": url,
        # 새 필드
        "speed_toplist": speed_bits["speed_toplist"],
        "speed_data_guide": speed_bits["speed_data_guide"],
    }
    return row

# ------------ 입출력 유틸 ------------
def load_input_urls(path: Path) -> list[dict]:
    """
    - CSV: uplusumobile_pricDetail_urls.csv (권장)
      필요한 컬럼: detail_url (선택 메타: kind, ctgr)
    - TXT: 각 줄에 URL
    """
    rows = []
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                url = (row.get("detail_url") or "").strip()
                if not url:
                    continue
                rows.append({
                    "detail_url": url,
                    "kind": row.get("kind"),
                    "ctgr": row.get("ctgr"),
                    "list_url": row.get("list_url"),
                })
    else:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                url = line.strip()
                if url:
                    rows.append({"detail_url": url, "kind": None, "ctgr": None, "list_url": None})
    # dedup by URL
    seen = set()
    uniq = []
    for r in rows:
        u = r["detail_url"]
        if u in seen:
            continue
        seen.add(u)
        uniq.append(r)
    return uniq

OUT_FIELDS = [
    "site",
    "kind",
    "ctgr",
    "seq",
    "ctgrId",
    "hpPpnSeq",
    "hpPpnCd",
    "upPpnCd",
    "devKdCd",
    "sbscTypCd2",
    "sbscTypCd3",
    "feeName",
    "feeType",
    "title",
    "feature_vol",
    "feature_limit",
    "feature_supply",
    "price_origin",
    "price_discount",
    "chips",
    # 새 컬럼 2개
    "speed_toplist",
    "speed_data_guide",
    "detail_url",
    "list_url",
]

def ensure_out_csv(path: Path):
    if not path.exists():
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(OUT_FIELDS)

def append_out_csv(path: Path, rows: list[dict]):
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUT_FIELDS)
        for r in rows:
            w.writerow(r)

# ------------ 메인 ------------
def main():
    in_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(IN_FILE)
    out_path = Path(OUT_CSV)
    ensure_out_csv(out_path)

    input_rows = load_input_urls(in_path)
    print(f"[입력 URL] {len(input_rows)}개")

    s = build_session()
    total_ok = 0
    total_bad = 0

    for i, meta in enumerate(input_rows, 1):
        url = meta["detail_url"]
        try:
            soup = fetch_soup(s, url)
            row = parse_detail_page(soup, url)

            # 상위 목록 메타가 있다면 보존
            row["kind"] = meta.get("kind")
            row["ctgr"] = meta.get("ctgr")
            row["list_url"] = meta.get("list_url")

            append_out_csv(out_path, [row])
            total_ok += 1
            if i % 10 == 0:
                print(f"  - 진행 {i}/{len(input_rows)}: 성공 {total_ok}, 실패 {total_bad}")
        except requests.RequestException as e:
            total_bad += 1
            print(f"[HTTP 오류] {url} -> {e}")
        except Exception as e:
            total_bad += 1
            print(f"[파싱 오류] {url} -> {e}")
        time.sleep(REQUEST_INTERVAL_SEC)

    print(f"[완료] 성공 {total_ok}, 실패 {total_bad} -> {OUT_CSV}")

if __name__ == "__main__":
    main()
