# EGMobile_scrape.py
# ------------------------------------------------------------
# 설치:
#   # Playwright 권장
#   pip install playwright beautifulsoup4 lxml
#   playwright install chromium
#
#   # Selenium 사용 시(옵션)
#   pip install selenium webdriver-manager beautifulsoup4 lxml
#
# 실행 예:
#   python EGMobile_scrape.py
#   python EGMobile_scrape.py --engine selenium
#   python EGMobile_scrape.py --csv egmobile_plans.csv
# ------------------------------------------------------------

import argparse
import csv
import logging
import re
import sys
from typing import Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

BASE = "https://www.egmobile.co.kr/"
LIST_URLS = [
    "https://www.egmobile.co.kr/charge/list?te=kt",
    "https://www.egmobile.co.kr/charge/list?te=lg",
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/118.0.0.0 Safari/537.36"
)

# --------- logging: 짧고 필요한 것만 ---------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("egmobile")
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)


# --------- 공통 유틸 ---------
def norm_text(node) -> str:
    if not node:
        return ""
    txt = node.get_text(" ", strip=True)
    # 공백 정리
    return " ".join(txt.split())


def extract_href_from_onclick(onclick: str) -> Optional[str]:
    """
    onclick="location.href='...'" 혹은 "location.href="...""
    또는 location.assign('...') 패턴 등을 최대한 커버
    """
    if not onclick:
        return None
    # location.href='...' or "..."
    m = re.search(r"location\.href\s*=\s*['\"]([^'\"]+)['\"]", onclick)
    if m:
        return m.group(1).strip()

    # location.assign('...' or "...")
    m = re.search(r"location\.assign\(\s*['\"]([^'\"]+)['\"]\s*\)", onclick)
    if m:
        return m.group(1).strip()

    # window.location='...'
    m = re.search(r"window\.location\s*=\s*['\"]([^'\"]+)['\"]", onclick)
    if m:
        return m.group(1).strip()

    return None


def parse_rows_from_html(html: str, source_url: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "lxml")
    rows = soup.select("tr[onclick]")
    logger.info(f"행 수: {len(rows)} | {source_url}")

    out: List[Dict[str, str]] = []
    for tr in rows:
        if tr.find("td") is None:
            continue

        data: Dict[str, str] = {}

        # href
        onclick = tr.get("onclick", "") or ""
        href = extract_href_from_onclick(onclick) or ""
        if href and not href.startswith("http"):
            href = urljoin(BASE, href)
        data["href"] = href

        # 각 TD의 class명을 키로 저장 (요청사항)
        for td in tr.find_all("td"):
            classes = td.get("class", [])
            if not classes:
                continue
            key = classes[0]

            if key == "fee":
                # fee 전체 + 세부 파트 분리
                data["fee"] = norm_text(td)
                fixed_price = td.find("span", class_="fixed_price")
                price = td.find("span", class_="price")
                data["fee_fixed_price"] = norm_text(fixed_price)
                data["fee_price"] = norm_text(price)

                # 남는 설명(예: "6개월이후 평생 9,900원") 추출
                remainder = data["fee"]
                for part in (data["fee_fixed_price"], data["fee_price"]):
                    if part:
                        remainder = remainder.replace(part, " ").strip()
                data["fee_note"] = " ".join(remainder.split())
            else:
                data[key] = norm_text(td)

        data["source_url"] = source_url
        # 최소 안전장치
        if any(data.get(k) for k in ("href", "name", "data", "phone", "txt", "fee")):
            out.append(data)

    return out


# --------- Playwright 수집 ---------
def fetch_html_playwright(url: str, wait_selector: str = "tr[onclick]", timeout_ms: int = 8000) -> str:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=USER_AGENT, locale="ko-KR")
        page = ctx.new_page()
        try:
            page.set_default_timeout(timeout_ms)
            page.goto(url, wait_until="domcontentloaded")
            # 리스트가 ajax로 채워지므로 잠깐 대기 + selector 등장까지 대기
            page.wait_for_timeout(500)
            page.wait_for_selector(wait_selector, state="attached")
            page.wait_for_timeout(200)
            return page.content()
        finally:
            ctx.close()
            browser.close()


# --------- Selenium 수집(옵션) ---------
def fetch_html_selenium(url: str, wait_selector: str = "tr[onclick]", timeout_sec: int = 8) -> str:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC

    # 드라이버 준비: webdriver-manager 사용(자동 다운로드) 시 아래 주석 해제 가능
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        driver_path = ChromeDriverManager().install()
        use_manager = True
    except Exception:
        driver_path = None
        use_manager = False

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(f"--user-agent={USER_AGENT}")
    options.add_argument("--lang=ko-KR")

    if use_manager:
        driver = webdriver.Chrome(driver_path, options=options)
    else:
        # 시스템 PATH에 chromedriver가 있어야 함
        driver = webdriver.Chrome(options=options)

    try:
        driver.set_page_load_timeout(timeout_sec)
        driver.get(url)
        WebDriverWait(driver, timeout_sec).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, wait_selector))
        )
        # 살짝 딜레이로 렌더링 안정화
        WebDriverWait(driver, timeout_sec).until(
            lambda d: len(d.find_elements(By.CSS_SELECTOR, wait_selector)) > 0
        )
        return driver.page_source
    finally:
        driver.quit()


# --------- 메인 로직 ---------
def crawl(urls: List[str], engine: str) -> List[Dict[str, str]]:
    all_rows: List[Dict[str, str]] = []
    for i, url in enumerate(urls, 1):
        logger.info(f"[{i}/{len(urls)}] {engine} | {url}")
        try:
            if engine == "playwright":
                html = fetch_html_playwright(url)
            elif engine == "selenium":
                html = fetch_html_selenium(url)
            else:
                raise ValueError("engine must be 'playwright' or 'selenium'")
            rows = parse_rows_from_html(html, url)
            all_rows.extend(rows)
        except Exception as e:
            logger.error(f"실패: {url} | {e}")
    return all_rows


def save_csv(rows: List[Dict[str, str]], out_path: str) -> None:
    if not rows:
        logger.warning("수집 결과 0건 - CSV 저장 생략")
        return

    # 모든 키 수집(동적 컬럼)
    keys: List[str] = []
    for r in rows:
        for k in r.keys():
            if k not in keys:
                keys.append(k)

    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    logger.info(f"CSV 저장 완료: {out_path} | 총 {len(rows)}건")


def main():
    parser = argparse.ArgumentParser(description="EGMobile 요금제 리스트 크롤러 (Playwright/Selenium + BeautifulSoup)")
    parser.add_argument("--engine", choices=["playwright", "selenium"], default="playwright",
                        help="렌더러 선택 (기본: playwright)")
    parser.add_argument("--csv", default="egmobile_plans.csv", help="저장할 CSV 경로 (기본: egmobile_plans.csv)")
    args = parser.parse_args()

    rows = crawl(LIST_URLS, engine=args.engine)
    logger.info(f"총 수집 건수: {len(rows)}")
    save_csv(rows, args.csv)


if __name__ == "__main__":
    main()
