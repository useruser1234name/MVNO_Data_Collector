import re
import time
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# ====== 설정 ======
MAIN_URL = "https://shakemobile.co.kr/M2Mobile/Set3G"
DETAIL_BASE = "https://shakemobile.co.kr/M2Mobile/feeDetail/"
OUT_DIR = Path("shakemobile_export")
HTML_DIR = OUT_DIR / "html"
REQUEST_DELAY = 0.8

# 특정 클래스만 추출하고 싶다면 지정 (None = 전체)
TARGET_CLASSES = None

# ====== 브라우저 세팅 ======
def setup_driver(headless=True):
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1400,900")

    # 일반적인 헤더 (사이트에서 UA 검사 대비)
    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/118.0.5993.90 Safari/537.36"
    )
    options.add_argument(f"--user-agent={user_agent}")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    return driver

def wait_ready(driver, timeout=15):
    WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )

# ====== 수집 함수 ======
def extract_fee_ids(driver):
    driver.get(MAIN_URL)
    wait_ready(driver)
    # feeDetail('...') 패턴 추출
    pattern = re.compile(r"feeDetail\('([^']+)'\)")
    html = driver.page_source
    ids = list(dict.fromkeys(pattern.findall(html)))
    return ids

def normalize(s):
    return re.sub(r"\s+", " ", s or "").strip()

def collect_class_texts(soup):
    class_map = {}
    for el in soup.find_all(class_=True):
        text = normalize(el.get_text(" ", strip=True))
        if not text:
            continue
        for cls in el.get("class", []):
            if TARGET_CLASSES and cls not in TARGET_CLASSES:
                continue
            if not re.match(r"^[A-Za-z0-9_\-]+$", cls):
                continue
            class_map.setdefault(cls, []).append(text)
    # 중복 제거 및 합침
    return {k: " | ".join(dict.fromkeys(v)) for k, v in class_map.items()}

def scrape_detail(driver, url):
    driver.get(url)
    wait_ready(driver)
    time.sleep(0.3)

    # Referer 헤더 설정 (일부 서버에서 필요)
    driver.execute_script(
        "Object.defineProperty(document, 'referrer', {get: () => 'https://shakemobile.co.kr/M2Mobile/Set3G'});"
    )

    html = driver.page_source
    safe_name = re.sub(r"[^A-Za-z0-9_\-]+", "_", url.replace(DETAIL_BASE, ""))
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    (HTML_DIR / f"{safe_name}.html").write_text(html, encoding="utf-8")

    soup = BeautifulSoup(html, "lxml")
    data = collect_class_texts(soup)
    data["__url"] = url
    return data

# ====== 실행 ======
def main():
    OUT_DIR.mkdir(exist_ok=True)
    driver = setup_driver(headless=True)
    try:
        print("[1] 메인페이지 접속 및 ID 수집")
        fee_ids = extract_fee_ids(driver)
        print(f" - 수집된 feeDetail ID 개수: {len(fee_ids)}")

        urls = [urljoin(DETAIL_BASE, fid) for fid in fee_ids]
        pd.DataFrame({"url": urls}).to_csv(OUT_DIR / "detail_urls.csv", index=False, encoding="utf-8-sig")

        print("[2] 상세 페이지 수집 및 파싱")
        records = []
        for i, url in enumerate(urls, 1):
            print(f"   {i}/{len(urls)} : {url}")
            rec = scrape_detail(driver, url)
            records.append(rec)
            time.sleep(REQUEST_DELAY)

        print("[3] CSV 저장")
        df = pd.DataFrame(records).fillna("")
        cols = ["__url"] + [c for c in df.columns if c != "__url"]
        df = df[cols]
        df.to_csv(OUT_DIR / "details_wide_by_class.csv", index=False, encoding="utf-8-sig")

        long_rows = []
        for r in records:
            url = r["__url"]
            for k, v in r.items():
                if k != "__url":
                    long_rows.append({"url": url, "class": k, "text": v})
        pd.DataFrame(long_rows).to_csv(OUT_DIR / "details_long_by_class.csv", index=False, encoding="utf-8-sig")

        print("완료")
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
