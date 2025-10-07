# ChanceMobile_scrape.py (fixed)
import argparse
import csv
import logging
import re
import sys
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlunparse, urlencode

from bs4 import BeautifulSoup

BASE = "https://chancemobile.co.kr/"
LIST_URLS = [
    "https://chancemobile.co.kr/view/plan/phone_plan.aspx",
]
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/118.0.0.0 Safari/537.36"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("chancemobile")
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)

def norm_text(node) -> str:
    if not node:
        return ""
    txt = node.get_text(" ", strip=True)
    return " ".join(txt.split())

def build_detail_url(gdcd: str, poscd: str) -> str:
    path = "/view/plan/phone_plan_detail.aspx"
    query = urlencode({"gdcd": gdcd, "poscd": poscd})
    return urlunparse(("https", "chancemobile.co.kr", path, "", query, ""))

def parse_fnMove_params(onclick: str) -> Optional[Tuple[str, str]]:
    if not onclick:
        return None
    m = re.search(
        r"fnMovePlanDetail\s*\(\s*['\"]?([^,'\")\s]+)['\"]?\s*,\s*['\"]?([^,'\")\s]+)['\"]?\s*\)",
        onclick,
        flags=re.IGNORECASE,
    )
    if not m:
        return None
    return m.group(1), m.group(2)

def pick_container(el):
    # onclick이 붙은 요소 자신이 컨테이너일 수도 있고, 보통은 tr/li/div 부모가 컨테이너
    if el.name in ("tr", "li", "div"):
        return el
    p = el.find_parent(["tr", "li", "div"])
    return p or el

def extract_class_text(container, cls: str) -> str:
    nodes = container.select(f".{cls}")
    if not nodes:
        return ""
    vals = [norm_text(n) for n in nodes if norm_text(n)]
    return " | ".join(vals)

def extract_td_columns(container) -> Dict[str, str]:
    out = {}
    tds = container.select("td")
    for i, td in enumerate(tds):
        txt = norm_text(td)
        if txt:
            out[f"td_{i}"] = txt
    return out

def extract_common_fields(container, row: Dict[str, str]):
    # 보편적으로 쓸 수 있는 필드들: 있으면 추가
    for cls in ["data", "data_wrap", "name", "title", "plan", "fee", "price", "txt", "desc"]:
        val = extract_class_text(container, cls)
        if val:
            row[cls] = val

def parse_rows_from_html(html: str, source_url: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "lxml")
    candidates = soup.select('[onclick*="fnMovePlanDetail"]')
    logger.info(f"감지된 onclick 요소: {len(candidates)} | {source_url}")

    out: List[Dict[str, str]] = []
    seen = set()

    for el in candidates:
        onclick = el.get("onclick") or ""
        params = parse_fnMove_params(onclick)
        if not params:
            continue
        gdcd, poscd = params
        href = build_detail_url(gdcd, poscd)
        if href in seen:
            continue
        seen.add(href)

        container = pick_container(el)
        row: Dict[str, str] = {
            "href": href,
            "gdcd": gdcd,
            "poscd": poscd,
            "source_url": source_url,
        }

        # 우선 클래스 기반 컬럼 채우기
        extract_common_fields(container, row)

        # .data / .data_wrap 둘 다 비었으면 한 단계 위 컨테이너도 시도
        if not row.get("data") and not row.get("data_wrap"):
            upper = container.find_parent(["tr", "li", "div"])
            if upper and upper != container:
                extract_common_fields(upper, row)

        # 그래도 비면 td 컬럼 보강
        if not any(row.get(k) for k in ("data", "data_wrap", "name", "title", "plan", "fee", "price", "txt", "desc")):
            row.update(extract_td_columns(container))

        # 최소: href 외에 뭔가 텍스트가 하나라도 있어야 저장
        if any(k for k, v in row.items() if k not in ("href", "gdcd", "poscd", "source_url") and v):
            out.append(row)
        else:
            # 그래도 남기고 싶다면 주석 해제
            # out.append(row)
            pass

    return out

def fetch_html_playwright(url: str, wait_selector: str = '[onclick*="fnMovePlanDetail"]', timeout_ms: int = 8000) -> str:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=USER_AGENT, locale="ko-KR")
        page = ctx.new_page()
        try:
            page.set_default_timeout(timeout_ms)
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(400)
            page.wait_for_selector(wait_selector, state="attached")
            page.wait_for_timeout(150)
            return page.content()
        finally:
            ctx.close()
            browser.close()

def fetch_html_selenium(url: str, wait_selector: str = '[onclick*="fnMovePlanDetail"]', timeout_sec: int = 8) -> str:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        driver_path = ChromeDriverManager().install()
        use_manager = True
    except Exception:
        driver_path = None
        use_manager = False

    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument(f"--user-agent={USER_AGENT}")
    opts.add_argument("--lang=ko-KR")
    driver = webdriver.Chrome(driver_path, options=opts) if use_manager else webdriver.Chrome(options=opts)
    try:
        driver.set_page_load_timeout(timeout_sec)
        driver.get(url)
        WebDriverWait(driver, timeout_sec).until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, wait_selector)))
        return driver.page_source
    finally:
        driver.quit()

def crawl(urls: List[str], engine: str) -> List[Dict[str, str]]:
    all_rows: List[Dict[str, str]] = []
    for i, url in enumerate(urls, 1):
        logger.info(f"[{i}/{len(urls)}] {engine} | {url}")
        try:
            if engine == "playwright":
                html = fetch_html_playwright(url)
            else:
                html = fetch_html_selenium(url)
            rows = parse_rows_from_html(html, url)
            logger.info(f"추출: {len(rows)}건 | {url}")
            all_rows.extend(rows)
        except Exception as e:
            logger.error(f"실패: {url} | {e}")
    return all_rows

def save_csv(rows: List[Dict[str, str]], out_path: str) -> None:
    if not rows:
        logger.warning("결과 0건 - CSV 저장 생략")
        return
    # 동적 컬럼 생성
    keys: List[str] = []
    for r in rows:
        for k in r.keys():
            if k not in keys:
                keys.append(k)
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    logger.info(f"CSV 저장 완료: {out_path} | {len(rows)}건")

def main():
    parser = argparse.ArgumentParser(description="ChanceMobile 요금제 리스트 크롤러 (Playwright/Selenium + BeautifulSoup)")
    parser.add_argument("--engine", choices=["playwright", "selenium"], default="playwright")
    parser.add_argument("--csv", default="chancemobile_plans.csv")
    args = parser.parse_args()
    rows = crawl(LIST_URLS, engine=args.engine)
    save_csv(rows, args.csv)

if __name__ == "__main__":
    main()
