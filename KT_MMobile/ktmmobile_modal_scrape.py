# -*- coding: utf-8 -*-
"""
KT M모바일 탭/아코디언 타이틀 스캐너 (Selenium)
- 메인탭: button[id^="rateListTab"]만
- 서브탭: 해당 메인패널 내부의 role=tab (id^=rateListTab 제외)
- 각 서브탭 범위에서 li.c-accordion__item > .c-accordion__head > .product__title 텍스트를 전부 리스트업
- 후속 동작용: 타이틀로 아코디언 열기(click_accordion_by_title) 제공
"""

import argparse
import re
import time
from typing import List, Dict, Optional

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

URL = "https://www.ktmmobile.com/rate/rateList.do"

def ts() -> str:
    return time.strftime("[%H:%M:%S]")

def norm(s: str) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", s).strip()

def setup_driver(headless: bool, slowmo: int) -> webdriver.Chrome:
    opts = ChromeOptions()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1440,900")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-notifications")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(options=opts)
    if slowmo > 0:
        driver.implicitly_wait(slowmo / 1000.0)
    return driver

def disable_blocking_ui(driver: webdriver.Chrome):
    js = """
    for (const sel of [
      '#pullProductCompare', '.rate-compare__floating', '.floating-compare',
      'button:has-text("요금제 비교함")', '.btn-compare', '.compare',
      '.ly-page--title', 'header', '#header', '.cookie', '.toast', '.banner', '.modal-backdrop'
    ]) {
      try {
        const el = document.querySelector(sel);
        if (el) el.style.pointerEvents = 'none';
      } catch (e) {}
    }
    """
    try:
        driver.execute_script(js)
    except Exception:
        pass

def scroll_pulse(driver: webdriver.Chrome, pulses: int = 3, delta: int = 1200, gap_ms: int = 120):
    for _ in range(pulses):
        try:
            driver.execute_script("window.scrollBy(0, arguments[0]);", delta)
            time.sleep(gap_ms/1000.0)
            driver.execute_script("window.scrollBy(0, arguments[0]);", int(-delta*0.6))
            time.sleep(gap_ms/1000.0)
        except Exception:
            break

def safe_click(driver: webdriver.Chrome, el) -> bool:
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    except Exception:
        pass
    try:
        el.click()
        return True
    except Exception:
        try:
            driver.execute_script("arguments[0].click();", el)
            return True
        except Exception:
            return False

def wait_panel_ready(driver: webdriver.Chrome, scope, timeout: int = 9) -> bool:
    sels = [
        "button.c-tabs__button[role='tab']:not([id^='rateListTab'])",
        ".runtime-data-insert.c-accordion__button",
        ".rate-content-wrap, ul.rate-content__list"
    ]
    end = time.time() + timeout
    while time.time() < end:
        for sel in sels:
            try:
                found = scope.find_elements(By.CSS_SELECTOR, sel)
                if any(e.is_displayed() for e in found):
                    return True
            except Exception:
                pass
        time.sleep(0.25)
    return False

# ---- 탭 수집 ----
def get_main_tabs(driver: webdriver.Chrome) -> List[Dict]:
    tabs = driver.find_elements(By.CSS_SELECTOR, "button.c-tabs__button[id^='rateListTab'][role='tab']")
    out: List[Dict] = []
    for b in tabs:
        try:
            name = norm(b.text.replace("현재 선택됨", ""))
            panel_id = b.get_attribute("aria-controls") or ""
            if name:
                out.append({"name": name, "el": b, "panel_id": panel_id})
        except Exception:
            continue
    return out

def get_subtabs_in_panel(panel_el) -> List[Dict]:
    try:
        subs = panel_el.find_elements(By.CSS_SELECTOR, "button.c-tabs__button[role='tab']")
    except Exception:
        return []
    out: List[Dict] = []
    for b in subs:
        try:
            bid = b.get_attribute("id") or ""
            if bid.startswith("rateListTab"):
                continue
            name = norm((b.text or "").replace("현재 선택됨", ""))
            code = b.get_attribute("data-rate-adsvc-ctg-cd") or ""
            pid  = b.get_attribute("aria-controls") or ""
            if name:
                out.append({"name": name, "el": b, "code": code, "panel_id": pid})
        except Exception:
            pass
    uniq, seen = [], set()
    for x in out:
        if x["name"] not in seen:
            uniq.append(x); seen.add(x["name"])
    return uniq

def wait_subtab_active(driver: webdriver.Chrome, btn, timeout: int = 6) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            if (btn.get_attribute("aria-selected") or "").lower() == "true":
                return True
        except Exception:
            pass
        time.sleep(0.15)
    return False

# ---- 핵심: 아코디언 타이틀 추출 & 타이틀로 열기 ----
def list_accordion_titles(panel_el, code: Optional[str]) -> List[str]:
    """
    패널 내에서 li.c-accordion__item에 있는 strong.product__title만 추출.
    - code가 있으면 해당 code로 필터링(ancestor li의 data-rate-adsvc-ctg-cd)
    - 없으면 패널 전체에서 추출
    """
    titles: List[str] = []
    try:
        if code:
            nodes = panel_el.find_elements(
                By.XPATH,
                ".//li[contains(@class,'c-accordion__item') and @data-rate-adsvc-ctg-cd=$code]"
                "//strong[contains(@class,'product__title')]",
                {"code": code}
            )
        else:
            nodes = panel_el.find_elements(By.CSS_SELECTOR, "li.c-accordion__item strong.product__title")
    except Exception:
        nodes = []

    for el in nodes:
        t = norm(el.text)
        if t:
            titles.append(t)

    # 중복 제거(순서 유지)
    uniq, seen = [], set()
    for t in titles:
        if t not in seen:
            uniq.append(t); seen.add(t)
    return uniq

def click_accordion_by_title(driver: webdriver.Chrome, panel_el, title: str) -> bool:
    """
    타이틀 텍스트로 해당 아코디언 헤더 버튼을 찾아 열기.
    """
    try:
        # 타이틀이 들어있는 li 항목을 찾은 뒤, 그 안의 버튼을 클릭
        li = panel_el.find_element(
            By.XPATH,
            ".//li[contains(@class,'c-accordion__item')][.//strong[contains(@class,'product__title') and normalize-space(text())=$txt]]",
            {"txt": title}
        )
        btn = li.find_element(By.CSS_SELECTOR, "button.c-accordion__button")
        return safe_click(driver, btn)
    except Exception:
        return False

# ---- 메인 플로우 ----
def main(url: str, headless: bool, slowmo: int):
    driver = setup_driver(headless=headless, slowmo=slowmo)
    wait = WebDriverWait(driver, 20)

    print(f"{ts()} [INFO] 이동: {url}")
    driver.get(url)
    try:
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "button.c-tabs__button[id^='rateListTab']")))
    except Exception:
        pass
    time.sleep(0.6)

    disable_blocking_ui(driver)
    tabs = get_main_tabs(driver)
    print(f"{ts()} [TABS] 메인탭: {[t['name'] for t in tabs]}")

    for mt in tabs:
        main_name = mt["name"]
        print(f"\n{ts()} [STEP] 메인탭 클릭: {main_name}")
        disable_blocking_ui(driver)
        if not safe_click(driver, mt["el"]):
            print(f"{ts()} [WARN] 메인탭 클릭 실패: {main_name}")
            continue
        time.sleep(0.35)

        # 메인 패널
        if mt["panel_id"]:
            try:
                main_panel = driver.find_element(By.ID, mt["panel_id"])
            except Exception:
                main_panel = driver.find_element(By.CSS_SELECTOR, "[role='tabpanel']")
        else:
            main_panel = driver.find_element(By.CSS_SELECTOR, "[role='tabpanel']")

        if not wait_panel_ready(driver, main_panel, 9):
            print(main_name)
            print(f"{ts()} [WARN] 패널 준비 실패: {main_name}")
            continue

        # 서브탭
        subs = get_subtabs_in_panel(main_panel)
        if subs:
            print(f"{main_name} [{', '.join([s['name'] for s in subs])}]")
            for st in subs:
                if not safe_click(driver, st["el"]):
                    print(f"{st['name']} 타이틀 0개 -> []")
                    continue
                wait_subtab_active(driver, st["el"], 6)
                scroll_pulse(driver, 2, 1000, 100)
                wait_panel_ready(driver, main_panel, 9)

                titles = list_accordion_titles(main_panel, st.get("code") or None)
                # 폴백(혹시 코드 매칭이 비어오면 전체에서 시도)
                if not titles:
                    titles = list_accordion_titles(main_panel, None)

                print(f"{st['name']} 아코디언 타이틀 {len(titles)}개 -> {titles}")

                # (참고) 특정 타이틀 열기 예시:
                # for t in titles:
                #     if click_accordion_by_title(driver, main_panel, t):
                #         time.sleep(0.2)
        else:
            # 서브탭 없음(예: 제휴 요금제)
            print(main_name)
            scroll_pulse(driver, 2, 1000, 100)
            wait_panel_ready(driver, main_panel, 9)
            titles = list_accordion_titles(main_panel, None)
            print(f"{main_name} 아코디언 타이틀 {len(titles)}개 -> {titles}")

    driver.quit()

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=URL)
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--slowmo", type=int, default=0, help="implicit wait(ms). 추천: 0")
    args = ap.parse_args()
    main(args.url, args.headless, args.slowmo)
