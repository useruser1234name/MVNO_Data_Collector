# sk7_crawl_all.py
import re
import sys
import csv
import time
import random
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
    # PHONE (LTE)
    "https://www.sk7mobile.com/prod/data/callingPlanList.do?refCode=PHONE&searchCallPlanType=PROD_LTE_TYPE_ALL&searchOrderby=6",
    # USIM
    "https://www.sk7mobile.com/prod/data/callingPlanList.do?refCode=USIM&searchCallPlanType=PROD_USIM_TYPE_ALL&searchOrderby=6",
]
VIEW_BASE = "https://www.sk7mobile.com/prod/data/callingPlanView.do"

OUT_CSV = "sk7_detail_all.csv"
FAILED_TXT = "sk7_detail_failed.txt"

REQUEST_INTERVAL_BASE = 0.5  # 매너타임(초)
REQUEST_INTERVAL_JITTER = 0.2  # ± 지터
WARMUP_COUNT = 5
WARMUP_DELAY_SEC = 1.0

# 고정 헤더
BASE_HEADERS = {
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

# ======================
# 유틸
# ======================
def build_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(BASE_HEADERS)
    retries = Retry(
        total=3,
        backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST"),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s

def sleep_politely(i: int):
    if i <= WARMUP_COUNT:
        time.sleep(WARMUP_DELAY_SEC)
    else:
        time.sleep(REQUEST_INTERVAL_BASE + random.uniform(-REQUEST_INTERVAL_JITTER, REQUEST_INTERVAL_JITTER))

def get_soup(session: requests.Session, url: str, referer: str | None = None) -> BeautifulSoup:
    headers = {}
    if referer:
        headers["Referer"] = referer
    r = session.get(url, timeout=15, headers=headers)
    if not r.encoding or r.encoding.lower() == "iso-8859-1":
        r.encoding = "utf-8"
    r.raise_for_status()
    return BeautifulSoup(r.text, "lxml")

def safe_text(node) -> str | None:
    return node.get_text(strip=True) if node else None

def parse_money(txt: str | None) -> int | None:
    if not txt:
        return None
    nums = re.findall(r"\d+", txt.replace(",", ""))
    return int("".join(nums)) if nums else None

def extract_qs(url: str) -> dict[str, list[str]]:
    try:
        return parse_qs(urlparse(url).query)
    except Exception:
        return {}

def extract_prodcd_from_url(url: str) -> str | None:
    qs = extract_qs(url)
    vals = qs.get("prodCd")
    return vals[0] if vals else None

def contains_korean(txt: str | None, keyword: str) -> bool:
    return (txt is not None) and (keyword in txt)

# ======================
# 리스트 → 상세 URL 생성
# ======================
TOTAL_RE = re.compile(r"\d+")
PROD_RE = re.compile(r"""fnSearchView\(['"](?P<prod>(?:PD|PC)[A-Za-z0-9]+)['"]\)""")

def parse_total(soup: BeautifulSoup) -> int | None:
    n = soup.select_one("p.total span")
    if not n:
        return None
    m = TOTAL_RE.search(n.get_text(strip=True))
    return int(m.group()) if m else None

def extract_prod_codes(soup: BeautifulSoup) -> list[str]:
    found = set()
    for tag in soup.find_all(attrs={"onclick": True}):
        m = PROD_RE.search(tag.get("onclick") or "")
        if m:
            found.add(m.group("prod"))
    return sorted(found)

def get_view_base_params(soup: BeautifulSoup, list_url: str) -> dict:
    ref = soup.select_one("input#refCode")
    typ = soup.select_one("input#searchCallPlanType")
    refCode = (ref.get("value").strip() if ref and ref.get("value") else None)
    callType = (typ.get("value").strip() if typ and typ.get("value") else None)

    if not (refCode and callType):
        qs = extract_qs(list_url)
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

# ======================
# 상세 파서
# ======================
def parse_detail_page(soup: BeautifulSoup, url: str) -> dict:
    # 메타
    prodCd = extract_prodcd_from_url(url)
    ref_in = soup.select_one("input#refCode")
    type_in = soup.select_one("input#searchCallPlanType")
    ord_in = soup.select_one("input#searchOrderby")
    refCode = ref_in.get("value").strip() if ref_in and ref_in.get("value") else None
    searchCallPlanType = type_in.get("value").strip() if type_in and type_in.get("value") else None
    searchOrderby = ord_in.get("value").strip() if ord_in and ord_in.get("value") else None

    badges = [safe_text(x) for x in soup.select(".badge-wp span") if safe_text(x)]
    title = safe_text(soup.select_one(".heading-depth1 h2.title")) or safe_text(soup.select_one("h2.title"))
    subtitle = safe_text(soup.select_one(".heading-depth1 p.sub span"))

    # 제공량(데이터/음성/문자)
    data_raw = voice_raw = sms_raw = None
    for li in soup.select("div.plan-info li"):
        label = safe_text(li.select_one("span.sr-only"))
        value = safe_text(li.select_one("p"))
        if not value:
            continue
        if label:
            if "데이터" in label:
                data_raw = value
            elif "음성" in label:
                voice_raw = value
            elif "문자" in label:
                sms_raw = value
        else:
            # 아이콘 기반 폴백
            cls_li = " ".join(li.get("class", []))
            cls_i_all = " ".join(
                " ".join(i.get("class", [])) for i in li.select("i")
            )
            cls = cls_li + " " + cls_i_all
            if "icon-data" in cls:
                data_raw = value
            elif "icon-call" in cls:
                voice_raw = value
            elif "icon-sms" in cls:
                sms_raw = value

    # SMS 폴백: heading-depth1 + plan-info 범위에서 "문자 100건" 류 찾기
    if sms_raw is None:
        scoped = soup.select_one(".heading-depth1") or soup.select_one(".plan-info")
        if scoped:
            m = re.search(r"문자\s*([\d,]+)\s*건", scoped.get_text(" ", strip=True))
            if m:
                sms_raw = f"{m.group(1)}건"

    # 가격(라벨 기반)
    price_base = price_promo = None
    for div in soup.select(".price-lst > div"):
        label = safe_text(div.select_one("em")) or ""
        valtxt = safe_text(div.select_one("p b")) or safe_text(div)
        won = parse_money(valtxt)
        if not won:
            continue
        if "기본료" in label and "프로모션" not in label:
            price_base = won
        elif "프로모션" in label and "기본료" in label:
            price_promo = won

    # QoS / 데이터+
    qos_text = None
    qos_speed_mbps = None
    daily_bonus_gb = None
    plus_suffix = None

    dp2 = safe_text(soup.select_one(".data-plus .item2 p"))
    if dp2:
        qos_text = dp2

    # 본문 보조문장(소진 시/무제한/Mbps 등)
    sub_sentences = " ".join(
        t for t in [
            qos_text,
            *[safe_text(p) for p in soup.select(".plan-sect p.tit-sub") if safe_text(p)]
        ] if t
    )

    # QoS 속도
    for source in [qos_text, sub_sentences, title, data_raw]:
        if not source:
            continue
        m = re.search(r"(\d+(?:\.\d+)?)\s*Mbps", source)
        if m:
            qos_speed_mbps = float(m.group(1))
            break

    # 일 XGB
    for source in [sub_sentences, title]:
        if not source:
            continue
        m = re.search(r"일\s*(\d+)\s*GB", source)
        if m:
            daily_bonus_gb = int(m.group(1))
            break

    # "GB+"
    plus_suffix = any(
        ("GB+" in s) for s in [title or "", data_raw or "", sub_sentences or ""]
    )

    # 숫자 정규화
    def parse_gb(text: str | None) -> float | None:
        if not text:
            return None
        m = re.search(r"(\d+(?:\.\d+)?)\s*GB", text.replace(",", ""))
        return float(m.group(1)) if m else None

    def parse_sms_count(text: str | None) -> int | None:
        if not text:
            return None
        m = re.search(r"(\d+)\s*건", text.replace(",", ""))
        return int(m.group(1)) if m else None

    data_gb = parse_gb(data_raw)
    sms_count = parse_sms_count(sms_raw)

    # 음성 타입(RM/RS) 추론
    voice_type = None
    vr = voice_raw or ""
    if any(k in (vr + " " + (title or "")) for k in ["무제한", "기본제공", "통화맘껏"]):
        voice_type = "RS"  # 통화맘껏
    elif any(ch.isdigit() for ch in vr) or "분" in vr:
        voice_type = "RM"  # 분제한

    # 요율표
    rate_data_won_per_mb = None
    rate_voice_won_per_sec = None
    rate_video_won_per_sec = None
    rate_sms_won_per_msg = None
    rate_lms_won_per_msg = None
    rate_mms_text_won_per_msg = None
    rate_mms_media_won_per_msg = None

    def to_number(txt: str | None) -> float | None:
        if not txt:
            return None
        n = "".join(re.findall(r"[\d\.]+", txt))
        return float(n) if n else None

    for tb in soup.select("table.tb"):
        # thead 검증 (항목/요율)
        headtxt = " ".join([safe_text(th) or "" for th in tb.select("thead th")])
        if not (("항목" in headtxt) and ("요율" in headtxt)):
            continue
        for tr in tb.select("tbody tr"):
            tds = tr.find_all("td")
            if len(tds) < 2:
                continue
            item = safe_text(tds[0]) or ""
            val = safe_text(tds[1]) or ""
            if "데이터" in item and rate_data_won_per_mb is None:
                rate_data_won_per_mb = to_number(val)
            elif "음성통화" in item and rate_voice_won_per_sec is None:
                rate_voice_won_per_sec = to_number(val)
            elif "영상통화" in item and rate_video_won_per_sec is None:
                rate_video_won_per_sec = to_number(val)
            elif "SMS" in item and rate_sms_won_per_msg is None:
                rate_sms_won_per_msg = to_number(val)
            elif "LMS" in item and rate_lms_won_per_msg is None:
                rate_lms_won_per_msg = to_number(val)
            elif "MMS_텍스트" in item and rate_mms_text_won_per_msg is None:
                rate_mms_text_won_per_msg = to_number(val)
            elif "MMS_멀티미디어" in item and rate_mms_media_won_per_msg is None:
                rate_mms_media_won_per_msg = to_number(val)

    # 혜택(표) & 테더링 한도
    benefits = []
    tethering_cap_gb = None
    # "요금제 이용 시 기본 혜택" 표
    for h3 in soup.select("h3.title"):
        text = safe_text(h3) or ""
        if "요금제 이용 시 기본 혜택" in text:
            sect = h3.find_parent("div", class_="plan-detail") or h3.parent
            table = sect.select_one("table.tb")
            if table:
                for tr in table.select("tbody tr"):
                    tds = tr.find_all("td")
                    if len(tds) >= 2:
                        name = safe_text(tds[0]) or ""
                        desc = safe_text(tds[1]) or ""
                        if name or desc:
                            benefits.append(f"{name}:{desc}")
                        # 테더링 한도 추출
                        if "테더링" in name + " " + desc and tethering_cap_gb is None:
                            m = re.search(r"(\d+)\s*GB", (name + " " + desc).replace(",", ""))
                            if m:
                                tethering_cap_gb = int(m.group(1))

    # 이벤트/혜택안내 섹션
    events = []
    for h3 in soup.select("h3.title"):
        t = (safe_text(h3) or "").strip()
        if "혜택 안내" in t or t.startswith("※"):
            # 같은 블록 내부 bullet 수집
            parent = h3.find_parent("div", class_="plan-detail") or h3.parent
            bullets = [safe_text(li) for li in parent.select(".lst-dot li") if safe_text(li)]
            if bullets:
                events.append(t + "::" + "|".join(bullets))

    return {
        "prodCd": prodCd,
        "refCode": refCode,
        "searchCallPlanType": searchCallPlanType,
        "searchOrderby": searchOrderby,
        "url": url,
        "badges": "|".join(badges) if badges else None,
        "title": title,
        "subtitle": subtitle,
        "data_raw": data_raw,
        "data_gb": data_gb,
        "daily_bonus_gb": daily_bonus_gb,
        "plus_suffix": plus_suffix,
        "qos_text": qos_text,
        "qos_speed_mbps": qos_speed_mbps,
        "voice_raw": voice_raw,
        "voice_type": voice_type,
        "sms_raw": sms_raw,
        "sms_count": sms_count,
        "price_base": price_base,
        "price_promo": price_promo,
        "rate_data_won_per_mb": rate_data_won_per_mb,
        "rate_voice_won_per_sec": rate_voice_won_per_sec,
        "rate_video_won_per_sec": rate_video_won_per_sec,
        "rate_sms_won_per_msg": rate_sms_won_per_msg,
        "rate_lms_won_per_msg": rate_lms_won_per_msg,
        "rate_mms_text_won_per_msg": rate_mms_text_won_per_msg,
        "rate_mms_media_won_per_msg": rate_mms_media_won_per_msg,
        "tethering_cap_gb": tethering_cap_gb,
        "extra_voice_benefit": None,   # (필요 시 본문에서 추가 패턴 확장)
        "benefits": "|".join(benefits) if benefits else None,
        "events": ";".join(events) if events else None,
    }

# ======================
# 저장/검증
# ======================
FIELDNAMES = [
    "prodCd","refCode","searchCallPlanType","searchOrderby","url",
    "badges","title","subtitle",
    "data_raw","data_gb","daily_bonus_gb","plus_suffix","qos_text","qos_speed_mbps",
    "voice_raw","voice_type","sms_raw","sms_count",
    "price_base","price_promo",
    "rate_data_won_per_mb","rate_voice_won_per_sec","rate_video_won_per_sec",
    "rate_sms_won_per_msg","rate_lms_won_per_msg","rate_mms_text_won_per_msg","rate_mms_media_won_per_msg",
    "tethering_cap_gb","extra_voice_benefit",
    "benefits","events",
]

def write_csv(rows: list[dict], csv_path: str):
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in FIELDNAMES})

def anomaly_checks(row: dict) -> list[str]:
    warns = []
    # 가격 역전
    pb, pp = row.get("price_base"), row.get("price_promo")
    if pb is not None and pp is not None and pb < pp:
        warns.append("price_base < price_promo")
    # RS인데 분 표시
    if row.get("voice_type") == "RS" and row.get("voice_raw") and any(d in row["voice_raw"] for d in ["분", "초"]):
        warns.append("RS but voice_raw shows minutes/seconds")
    # 요율표 전부 결측
    if all(row.get(k) is None for k in [
        "rate_data_won_per_mb","rate_voice_won_per_sec","rate_video_won_per_sec",
        "rate_sms_won_per_msg","rate_lms_won_per_msg","rate_mms_text_won_per_msg","rate_mms_media_won_per_msg"
    ]):
        warns.append("rate_table_empty")
    return warns

# ======================
# 메인
# ======================
def main():
    s = build_session()

    # 1) 두 리스트에서 상세 URL 전수
    all_detail_urls = []
    for list_url in LIST_URLS:
        soup = get_soup(s, list_url)
        total = parse_total(soup)
        prods = extract_prod_codes(soup)
        base_params = get_view_base_params(soup, list_url)
        detail_urls = [make_view_url(base_params, code) for code in prods]
        print(f"[LIST] {list_url}")
        print(f" - 표기 총건수: {total} / 추출 prodCd: {len(prods)} / 상세URL: {len(detail_urls)}")
        all_detail_urls.extend(detail_urls)

    # 중복 제거(순서 유지)
    seen = set()
    uniq_urls = []
    for u in all_detail_urls:
        if u not in seen:
            seen.add(u)
            uniq_urls.append(u)

    print(f"\n[총 상세 URL] {len(uniq_urls)} (중복 제거 후)")
    rows = []
    failed = []

    # 2) 상세 수집
    for i, url in enumerate(uniq_urls, 1):
        try:
            soup = get_soup(s, url, referer="https://www.sk7mobile.com/prod/data/callingPlanList.do")
            # 핵심 엘리먼트 존재 검증(반스크래핑/빈페이지 감지)
            if not soup.select_one("h2.title"):
                raise RuntimeError("empty_or_blocked_html (no h2.title)")
            row = parse_detail_page(soup, url)
            rows.append(row)

            if i % 20 == 0 or i == len(uniq_urls):
                print(f"  - 진행 {i}/{len(uniq_urls)} … 예: {row.get('prodCd')} / {row.get('title')}")
        except requests.RequestException as e:
            failed.append((url, f"HTTP {e}"))
            print(f"✗ HTTP 오류: {url} -> {e}")
        except Exception as e:
            failed.append((url, f"PARSE {e}"))
            print(f"✗ 파싱 오류: {url} -> {e}")
        finally:
            sleep_politely(i)

    # 3) 저장
    write_csv(rows, OUT_CSV)

    if failed:
        with open(FAILED_TXT, "w", encoding="utf-8") as f:
            for u, why in failed:
                f.write(f"{why}\t{u}\n")

    # 4) 요약/이상치
    print("\n[요약]")
    print(f"- 성공: {len(rows)}")
    print(f"- 실패: {len(failed)}")
    if failed:
        print("  일부 실패 샘플:")
        for u, why in failed[:5]:
            print("   ", why, u)

    warn_count = 0
    for r in rows:
        warns = anomaly_checks(r)
        if warns:
            warn_count += 1
    if warn_count:
        print(f"- 이상치 경고 감지: {warn_count}건 (가격 역전/요율표 누락 등)")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n중단됨.")
        sys.exit(130)
    except Exception as e:
        print(f"치명적 오류: {e}", file=sys.stderr)
        sys.exit(1)
