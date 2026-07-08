# pip install requests beautifulsoup4 lxml
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import csv

BASE = "https://www.sugarmobile.co.kr"
URLS = [
    "https://www.sugarmobile.co.kr/rate_plan.do?type=T006",  # LTE
    "https://www.sugarmobile.co.kr/rate_plan.do?type=T005",  # 5G
    "https://www.sugarmobile.co.kr/rate_plan.do?type=T003",  # 특수요금
    "https://www.sugarmobile.co.kr/rate_plan.do?type=T004",  # 선불 요금제
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/116.0.0.0 Safari/537.36"
    )
}

def get_soup(url: str) -> BeautifulSoup:
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding
    return BeautifulSoup(resp.text, "lxml")

def main():
    all_urls = []
    for page_url in URLS:
        soup = get_soup(page_url)

        cards = soup.select("li.card_list_item a.card_rate_link[href]")
        if not cards:
            print(f"[경고] 카드 링크 없음: {page_url}")
            continue

        for a in cards:
            href = a.get("href")
            abs_url = urljoin(BASE + "/", href)
            all_urls.append([abs_url])

    # CSV 저장 (rateplan_url만)
    csv_name = "sugarmobile_rateplan_urls.csv"
    with open(csv_name, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["rateplan_url"])
        writer.writerows(all_urls)

    print(f"[총 {len(all_urls)}개 링크 저장 완료] {csv_name}")

if __name__ == "__main__":
    main()
