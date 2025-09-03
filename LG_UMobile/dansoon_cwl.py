# -*- coding: utf-8 -*-
"""
U+ 유모바일 요금제 페이지에서
.payment-accordian-card 카드들을 모두 펼친 뒤
각 카드의 HTML/텍스트를 통째로 덤프합니다.
결과물:
  - uplus_cards/card_000.html, card_000.txt, ...
  - uplus_cards/cards_combined.html (전체 카드 합본)
  - uplus_cards/cards_dump.json (텍스트/HTML 요약)
필요: pip install selenium webdriver-manager beautifulsoup4
"""

import json
import time
from pathlib import Path
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

URL = "https://www.uplusumobile.com/product/pric/phone/pricList"
OUTDIR = Path("uplus_cards")
OUTDIR.mkdir(exist_ok=True)

def setup_driver():
    opts = Options()
    opts.add_argument("--headless=new")   # 필요시 주석 처리
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1600,2400")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    # 👇 여기서 capability를 옵션 객체에 직접 추가
    opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=opts
    )
    return driver

def full_scroll(driver, passes=8, sleep_sec=0.6):
    last_h = 0
    for _ in range(passes):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(sleep_sec)
        h = driver.execute_script("return document.body.scrollHeight")
        if h == last_h:
            break
        last_h = h

def expand_within_card(driver, card):
    """
    카드 내부의 아코디언/토글을 가능한 한 모두 펼칩니다.
    - aria-expanded="false" 버튼/토글
    - role='button' 요소
    - class에 accordion/accordian/toggle 포함
    - '더보기', '펼치기', '전체보기' 텍스트 포함
    """
    selectors = [
        "[aria-expanded='false']",
        "[role='button']",
        "*[class*='accordion']",
        "*[class*='accordian']",
        "*[class*='toggle']",
        "button", "summary", "a"
    ]
    text_keys = ["더보기", "펼치기", "전체보기", "more", "load more", "보기"]

    # 여러 번 시도(동적으로 생기는 컨텐츠 대비)
    for _ in range(4):
        clickable = []
        for sel in selectors:
            try:
                clickable += card.find_elements(By.CSS_SELECTOR, sel)
            except Exception:
                pass

        # 중복 제거
        uniq = []
        seen = set()
        for el in clickable:
            try:
                key = el.id
            except Exception:
                continue
            if key not in seen:
                seen.add(key)
                uniq.append(el)

        clicked = 0
        for el in uniq:
            try:
                # 텍스트 기준 필터
                txt = (el.text or "").strip().lower()
                if (el.get_attribute("aria-expanded") == "false") or \
                   any(k in txt for k in [k.lower() for k in text_keys]) or \
                   "accordion" in (el.get_attribute("class") or "").lower() or \
                   "accordian" in (el.get_attribute("class") or "").lower() or \
                   "toggle" in (el.get_attribute("class") or "").lower():

                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                    time.sleep(0.15)
                    # 클릭 시도 (가려짐/막힘 방지)
                    driver.execute_script("arguments[0].click();", el)
                    clicked += 1
                    time.sleep(0.35)
            except Exception:
                continue

        if clicked == 0:
            break  # 더 펼칠 것 없음

def dump_cards(driver):
    # 카드들 대기(필요시 선택자 조정)
    WebDriverWait(driver, 15).until(
        EC.presence_of_all_elements_located((By.CSS_SELECTOR, ".payment-accordian-card"))
    )
    cards = driver.find_elements(By.CSS_SELECTOR, ".payment-accordian-card")
    print(f"[info] 카드 수: {len(cards)}")

    data = []
    combined_html_parts = []

    for idx, card in enumerate(cards):
        try:
            # 카드 하나씩 화면 중앙으로
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", card)
            time.sleep(0.2)

            # 카드 내부 아코디언/토글을 모두 펼침
            expand_within_card(driver, card)
            time.sleep(0.2)

            # outerHTML 추출
            html = driver.execute_script("return arguments[0].outerHTML;", card)
            # 텍스트 추출
            text = BeautifulSoup(html, "lxml").get_text("\n", strip=True)

            # 파일 저장
            html_path = OUTDIR / f"card_{idx:03d}.html"
            txt_path  = OUTDIR / f"card_{idx:03d}.txt"
            html_path.write_text(html, encoding="utf-8")
            txt_path.write_text(text, encoding="utf-8")

            combined_html_parts.append(html)
            data.append({"index": idx, "text": text, "html_path": str(html_path)})

            print(f"[ok] 저장: {html_path.name} / {txt_path.name}")

        except Exception as e:
            print(f"[warn] 카드 {idx} 처리 중 예외: {e}")

    # 합본/JSON 저장
    (OUTDIR / "cards_combined.html").write_text(
        "<!doctype html><meta charset='utf-8'>\n" + "\n".join(combined_html_parts),
        encoding="utf-8"
    )
    (OUTDIR / "cards_dump.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"[done] 합본/JSON 저장 완료")

def main():
    driver = setup_driver()
    try:
        driver.get(URL)
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))

        # 지연 로딩 대비 전체 스크롤
        full_scroll(driver, passes=8, sleep_sec=0.6)

        # 한 번 더 스크롤(네트워크 로딩 유도)
        full_scroll(driver, passes=4, sleep_sec=0.6)

        # 카드 덤프
        dump_cards(driver)

    finally:
        driver.quit()

if __name__ == "__main__":
    main()
