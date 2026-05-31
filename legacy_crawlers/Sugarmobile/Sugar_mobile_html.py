# pip install requests beautifulsoup4 lxml pandas
import csv
import requests
from bs4 import BeautifulSoup
from collections import defaultdict, OrderedDict
import pandas as pd

INPUT_URL_CSV = "sugarmobile_rateplan_urls.csv"     # rateplan_url 열을 가진 입력 CSV
OUTPUT_CSV     = "sugarmobile_rateplan_by_class.csv"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/116.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Connection": "keep-alive",
    "Referer": "https://www.sugarmobile.co.kr/",
}

# class별로 텍스트를 모을지, inner HTML을 모을지 선택
AGGREGATE_MODE = "text"  # "text" 혹은 "html"

def get_soup(url: str) -> BeautifulSoup:
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    if not r.encoding or r.encoding.lower() == "iso-8859-1":
        r.encoding = r.apparent_encoding
    return BeautifulSoup(r.text, "lxml")

def load_rateplan_urls(csv_path: str):
    urls = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if "rateplan_url" not in reader.fieldnames:
            raise RuntimeError("입력 CSV에 'rateplan_url' 컬럼이 없습니다.")
        for row in reader:
            u = (row.get("rateplan_url") or "").strip()
            if u:
                urls.append(u)
    if not urls:
        raise RuntimeError("가져올 rateplan_url 이 없습니다.")
    return urls

def extract_class_aggregates(soup: BeautifulSoup) -> dict:
    """
    문서 내 class 속성이 있는 모든 태그를 순회하며
    동일한 class 조합(공백으로 구분되는 문자열)을 key로 모아 텍스트/HTML을 집계.
    """
    bucket = defaultdict(list)
    for el in soup.find_all(class_=True):
        classes = el.get("class")  # 리스트
        if not classes:
            continue
        # 원본 순서를 유지한 문자열 키로 사용
        key = " ".join(classes)

        if AGGREGATE_MODE == "html":
            content = el.decode()  # element의 inner가 아닌 element 전체 HTML
        else:
            # separator로 공백을 두어 텍스트가 붙지 않게 함
            content = el.get_text(separator=" ", strip=True)

        if content:
            bucket[key].append(content)

    # 같은 class에서 수집된 여러 요소 텍스트/HTML을 하나의 문자열로 병합
    # 중복 텍스트가 매우 많다면 set으로 중복 제거 가능(필요 시 주석 해제)
    aggregated = {}
    for k, lst in bucket.items():
        # lst = list(OrderedDict.fromkeys(lst))  # 중복 제거를 원하면 사용
        aggregated[k] = " | ".join(lst)
    return aggregated

def main():
    urls = load_rateplan_urls(INPUT_URL_CSV)

    # 1패스: 전체 문서에서 등장하는 class 컬럼 집합 수집
    all_class_keys = set()
    per_url_rows = []

    for url in urls:
        soup = get_soup(url)
        class_map = extract_class_aggregates(soup)
        all_class_keys.update(class_map.keys())
        # 나중에 DataFrame으로 만들기 위해 임시 저장
        row = {"rateplan_url": url}
        row.update(class_map)
        per_url_rows.append(row)

    # 컬럼 순서: rateplan_url + 정렬된 class 키
    ordered_cols = ["rateplan_url"] + sorted(all_class_keys)

    # DataFrame 생성 (없는 칼럼은 NaN -> 공백으로 채움)
    df = pd.DataFrame(per_url_rows, columns=ordered_cols).fillna("")

    # CSV 저장
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"[완료] {OUTPUT_CSV} 저장 (행={len(df)}, 열={len(df.columns)})")
    print(f"집계 모드: {AGGREGATE_MODE} / 고유 class 컬럼 수: {len(all_class_keys)}")

if __name__ == "__main__":
    main()
