# uplusumobile_collect_urls.py
import csv
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


LIST_URLS = [
    "https://www.uplusumobile.com/product/pric/usim/pricList?fltrTypeCtgr=LTE",
    "https://www.uplusumobile.com/product/pric/usim/pricList?fltrTypeCtgr=SPCL",
    "https://www.uplusumobile.com/product/pric/usim/pricList?fltrTypeCtgr=5G",
    "https://www.uplusumobile.com/product/pric/phone/pricList?fltrTypeCtgr=LTE",
    "https://www.uplusumobile.com/product/pric/phone/pricList?fltrTypeCtgr=5G",
    "https://www.uplusumobile.com/product/pric/phone/pricList?fltrTypeCtgr=SPCL",
]

DETAIL_BASE = "https://www.uplusumobile.com/product/pric/pricDetail"

OUT_CSV = "uplusumobile_pricDetail_urls.csv"
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


def parse_meta_from_list_url(list_url: str) -> dict:
    """
    예) /product/pric/usim/pricList?fltrTypeCtgr=LTE
    -> kind=usim|phone, ctgr=LTE|5G|SPCL
    """
    pu = urlparse(list_url)
    parts = [p for p in pu.path.split("/") if p]
    kind = None
    try:
        # .../pric/<kind>/pricList
        kind_idx = parts.index("pric") + 1
        kind = parts[kind_idx]
    except Exception:
        kind = None
    qs = parse_qs(pu.query)
    ctgr = (qs.get("fltrTypeCtgr") or [None])[0]
    return {"kind": kind, "ctgr": ctgr}


def make_detail_url(seq: str, upPpnCd: str, devKdCd: str) -> str:
    qs = {"seq": seq, "upPpnCd": upPpnCd, "devKdCd": devKdCd}
    return f"{DETAIL_BASE}?{urlencode(qs)}"


def extract_detail_urls_from_list(soup: BeautifulSoup) -> list[dict]:
    """
    목록 페이지에서 '비교하기' 버튼의 data-* 속성 추출.
    - 필수: data-hp-ppn-seq, data-up-ppn-cd, data-dev-kd-cd
    - 선택: data-ppn-cd (참고용)
    """
    rows = []
    # data 속성 기반이 가장 견고
    buttons = soup.select("button[data-hp-ppn-seq][data-up-ppn-cd][data-dev-kd-cd]")
    for b in buttons:
        seq = b.get("data-hp-ppn-seq")
        up = b.get("data-up-ppn-cd")
        dev = b.get("data-dev-kd-cd")
        ppn = b.get("data-ppn-cd")  # 참고(사용 안 해도 OK)
        if not (seq and up and dev):
            continue
        rows.append(
            {
                "seq": seq.strip(),
                "upPpnCd": up.strip(),
                "devKdCd": dev.strip(),
                "ppnCd": (ppn or "").strip() or None,
            }
        )
    return rows


def ensure_csv(path: Path):
    if not path.exists():
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(
                [
                    "site",
                    "kind",
                    "ctgr",
                    "seq",
                    "upPpnCd",
                    "devKdCd",
                    "ppnCd",
                    "detail_url",
                ]
            )


def append_rows(path: Path, rows: list[dict]):
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "site",
                "kind",
                "ctgr",
                "seq",
                "upPpnCd",
                "devKdCd",
                "ppnCd",
                "detail_url",
            ],
        )
        for r in rows:
            w.writerow(r)


def main():
    out_path = Path(OUT_CSV)
    ensure_csv(out_path)

    s = build_session()
    seen_keys: set[tuple] = set()  # (seq, upPpnCd, devKdCd)

    total = 0
    for list_url in LIST_URLS:
        try:
            meta = parse_meta_from_list_url(list_url)
            soup = fetch_soup(s, list_url)
            cand = extract_detail_urls_from_list(soup)

            rows = []
            for c in cand:
                key = (c["seq"], c["upPpnCd"], c["devKdCd"])
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                detail = make_detail_url(c["seq"], c["upPpnCd"], c["devKdCd"])
                rows.append(
                    {
                        "site": "uplusumobile",
                        "kind": meta["kind"],
                        "ctgr": meta["ctgr"],
                        "seq": c["seq"],
                        "upPpnCd": c["upPpnCd"],
                        "devKdCd": c["devKdCd"],
                        "ppnCd": c["ppnCd"],
                        "detail_url": detail,
                    }
                )

            append_rows(out_path, rows)
            total += len(rows)
            print(f"[OK] {list_url} -> {len(rows)}개 수집 (누적 {total})")

        except requests.RequestException as e:
            print(f"[HTTP 오류] {list_url} -> {e}")
        except Exception as e:
            print(f"[파싱 오류] {list_url} -> {e}")
        time.sleep(REQUEST_INTERVAL_SEC)

    print(f"[완료] 총 {total}개 URL 저장 -> {OUT_CSV}")


if __name__ == "__main__":
    main()
