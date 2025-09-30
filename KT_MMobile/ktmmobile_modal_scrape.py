# -*- coding: utf-8 -*-
"""
KT M모바일 탭/아코디언 헤더 메타 스캐너 + 확장 (Selenium, Deep Logging)
- 메인탭: button[id^="rateListTab"]만
- 서브탭: 해당 메인패널 내부 role=tab (id^=rateListTab 제외)
- 각 서브탭 '자체 패널(sub_panel)' 스코프에서 보이는 버튼만 대상으로 아코디언 헤더 메타 수집:
  * title(.product__title), sub(.product__sub)
  * btn_id, aria_controls, code(data-rate-adsvc-ctg-cd), expanded, btn_class
- 5G 섞임 방지: 타이틀이 있는 항목들의 코드 집합만 최종 채택(있을 때)
- 수집 메타 기반 클릭/확장 → 패널 확장 완료까지 대기
- 콘솔에 전구간 상세 로그 주입
"""

import argparse
import re
import time
from typing import List, Dict, Optional, Any, Tuple

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

URL = "https://www.ktmmobile.com/rate/rateList.do"

# ------------ LOGGING ------------
DEBUG = False

def ts() -> str:
    return time.strftime("[%H:%M:%S]")

def info(msg: str):  print(f"{ts()} [INFO] {msg}")
def step(msg: str):  print(f"\n{ts()} [STEP] {msg}")
def warn(msg: str):  print(f"{ts()} [WARN] {msg}")
def dbg(msg: str):
    if DEBUG:
        print(f"{ts()} [DEBUG] {msg}")

# ------------ UTILS ------------
def norm(s: str) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", s).strip()

def xpath_literal(s: str) -> str:
    # XPath 안전 리터럴
    if "'" not in s:
        return f"'{s}'"
    if '"' not in s:
        return f'"{s}"'
    parts = s.split("'")
    return "concat(" + ", \"'\", ".join(f"'{p}'" for p in parts) + ")"

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
      '.ly-page--title', 'header', '#header', '.cookie', '.toast', '.banner', '.modal-backdrop'
    ]) { try { const el = document.querySelector(sel); if (el) el.style.pointerEvents = 'none'; } catch (e) {} }
    """
    try:
        driver.execute_script(js)
        dbg("Blocking UI elements pointer-events:none 적용")
    except Exception:
        pass

def scroll_pulse(driver: webdriver.Chrome, pulses: int = 2, delta: int = 1000, gap_ms: int = 100):
    for i in range(pulses):
        try:
            driver.execute_script("window.scrollBy(0, arguments[0]);", delta)
            time.sleep(gap_ms/1000.0)
            driver.execute_script("window.scrollBy(0, arguments[0]);", int(-delta*0.6))
            time.sleep(gap_ms/1000.0)
            dbg(f"스크롤 펄스 {i+1}/{pulses}")
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
                    dbg(f"패널 준비 OK by selector: {sel}")
                    return True
            except Exception:
                pass
        time.sleep(0.25)
    return False

# ---- 탭 수집 ----
def get_main_tabs(driver: webdriver.Chrome) -> List[Dict[str, Any]]:
    tabs = driver.find_elements(By.CSS_SELECTOR, "button.c-tabs__button[id^='rateListTab'][role='tab']")
    out: List[Dict[str, Any]] = []
    for b in tabs:
        try:
            name = norm(b.text.replace("현재 선택됨", ""))
            panel_id = b.get_attribute("aria-controls") or ""
            if name:
                out.append({"name": name, "el": b, "panel_id": panel_id})
        except Exception:
            continue
    return out

def get_subtabs_in_panel(panel_el) -> List[Dict[str, Any]]:
    try:
        subs = panel_el.find_elements(By.CSS_SELECTOR, "button.c-tabs__button[role='tab']")
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for b in subs:
        try:
            bid = b.get_attribute("id") or ""
            if bid.startswith("rateListTab"):  # 메인탭은 제외
                continue
            name = norm((b.text or "").replace("현재 선택됨", ""))
            code = b.get_attribute("data-rate-adsvc-ctg-cd") or ""
            pid  = b.get_attribute("aria-controls") or ""
            out.append({"name": name, "el": b, "code": code, "panel_id": pid})
        except Exception:
            pass
    # 텍스트 기준 dedup
    uniq, seen = [], set()
    for x in out:
        if x["name"] and x["name"] not in seen:
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

# ---- 유틸: 클래스/표시 판단 ----
def element_has_class(driver: webdriver.Chrome, el, class_name: str) -> bool:
    try:
        return bool(driver.execute_script(
            "return arguments[0].classList && arguments[0].classList.contains(arguments[1]);",
            el, class_name
        ))
    except Exception:
        return False

def is_panel_visible(driver: webdriver.Chrome, panel_el) -> bool:
    try:
        return driver.execute_script(
            "const el=arguments[0]; if(!el) return false;"
            "const st=getComputedStyle(el); return st.display!=='none' && el.offsetHeight>0;",
            panel_el
        )
    except Exception:
        return False

# ---- 아코디언 헤더 메타 수집 (보이는 버튼만) + 타이틀/코드 기반 정제 ----
def collect_accordion_meta(panel_el, code: Optional[str]) -> List[Dict[str, Any]]:
    """
    sub_panel 범위에서 보이는 버튼만 순회 → 메타 수집.
    이후 '타이틀이 있는 항목들의 코드 집합'을 계산해 있으면 그 코드에 속한 항목만 유지.
    """
    result_raw: List[Dict[str, Any]] = []
    dropped_hidden = dropped_code = dropped_no_title = 0

    try:
        btns = panel_el.find_elements(By.CSS_SELECTOR, "li.c-accordion__item button.c-accordion__button")
    except Exception:
        btns = []

    dbg(f"sub_panel 버튼 후보 총 {len(btns)}")

    for btn in btns:
        try:
            if not btn.is_displayed():
                dropped_hidden += 1
                continue

            # 조상 li
            try:
                li = btn.find_element(By.XPATH, "./ancestor::li[contains(@class,'c-accordion__item')]")
            except Exception:
                dropped_hidden += 1
                continue

            # 코드
            li_code  = (li.get_attribute("data-rate-adsvc-ctg-cd") or "").strip()
            btn_code = (btn.get_attribute("data-rate-adsvc-ctg-cd") or "").strip()
            eff_code = btn_code or li_code

            if code and eff_code and code != eff_code:
                dropped_code += 1
                continue  # 서브탭 코드 명시 시 불일치 제거

            # 타이틀/서브
            try:
                title_el = li.find_element(By.CSS_SELECTOR, ".product__title-wrap .product__title, strong.product__title")
                title = norm(title_el.text)
            except Exception:
                title = ""

            try:
                sub_el = li.find_element(By.CSS_SELECTOR, ".product__title-wrap .product__sub, .product__sub")
                sub = norm(sub_el.text)
            except Exception:
                sub = ""

            btn_id = btn.get_attribute("id") or ""
            aria_controls = btn.get_attribute("aria-controls") or ""
            aria_expanded = (btn.get_attribute("aria-expanded") or "").lower() == "true"
            btn_class = btn.get_attribute("class") or ""

            result_raw.append({
                "title": title,
                "sub": sub,
                "btn_id": btn_id,
                "aria_controls": aria_controls,
                "code": eff_code,
                "expanded": aria_expanded,
                "btn_class": btn_class,
            })

        except Exception:
            continue

    # 타이틀이 있는 항목들의 코드 집합 추출
    titleful_codes = {r["code"] for r in result_raw if (r["title"] or "").strip()}
    dbg(f"titleful_codes = {sorted(list(titleful_codes)) if titleful_codes else '∅'}")

    # 코드 집합이 있으면 그 코드에 속한 것만 보존(빈 타이틀 노이즈 정리)
    if titleful_codes:
        result: List[Dict[str, Any]] = []
        for r in result_raw:
            if r["code"] in titleful_codes:
                result.append(r)
            else:
                dropped_no_title += 1
        dbg(f"정제: 원본 {len(result_raw)} → 최종 {len(result)} (숨김:{dropped_hidden}, 코드불일치:{dropped_code}, 무타이틀제거:{dropped_no_title})")
        return result

    dbg(f"정제: 타이틀 보유 코드가 없어 원본 유지 ({len(result_raw)}) (숨김:{dropped_hidden}, 코드불일치:{dropped_code})")
    return result_raw

# ---- 아코디언 찾기/열기 ----
def locate_btn_li_panel(driver: webdriver.Chrome, panel_el, meta: Dict[str, Any]) -> Tuple[Optional[object], Optional[object], Optional[object]]:
    btn = None
    li  = None
    pnl = None

    # 1) btn_id 우선 (sub_panel 범위)
    bid = (meta.get("btn_id") or "").strip()
    if bid:
        try:
            btn = panel_el.find_element(By.ID, bid)
            dbg(f"btn_id로 버튼획득: {bid}")
        except Exception:
            btn = None

    # 2) aria-controls 매칭 (sub_panel 범위)
    if not btn:
        ac = (meta.get("aria_controls") or "").strip()
        if ac:
            sel = f"button.c-accordion__button[aria-controls='{ac}']"
            try:
                btn = panel_el.find_element(By.CSS_SELECTOR, sel)
                dbg(f"aria-controls로 버튼획득: {ac}")
            except Exception:
                btn = None

    # 3) 타이틀 매칭(폴백; sub_panel 범위)
    if not btn:
        title = (meta.get("title") or "").strip()
        if title:
            xp = (
                ".//li[contains(@class,'c-accordion__item')]"
                f"[.//strong[contains(@class,'product__title') and normalize-space()={xpath_literal(title)}]]"
                "//button[contains(@class,'c-accordion__button')]"
            )
            try:
                btn = panel_el.find_element(By.XPATH, xp)
                dbg(f"타이틀 XPath로 버튼획득: {title}")
            except Exception:
                btn = None

    # li
    if btn:
        try:
            li = btn.find_element(By.XPATH, "./ancestor::li[contains(@class,'c-accordion__item')]")
        except Exception:
            li = None

    # panel (sub_panel 범위)
    ac2 = (meta.get("aria_controls") or "").strip()
    if ac2:
        try:
            pnl = panel_el.find_element(By.ID, ac2)
        except Exception:
            pnl = None
    if (pnl is None) and li:
        try:
            pnl = li.find_element(By.CSS_SELECTOR, ".c-accordion__panel")
        except Exception:
            pnl = None

    return btn, li, pnl

def open_accordion_and_wait(driver: webdriver.Chrome, btn, pnl, timeout: int = 8) -> bool:
    # 이미 확장?
    try:
        expanded_btn = (btn.get_attribute("aria-expanded") or "").lower() == "true"
    except Exception:
        expanded_btn = False
    expanded_pnl = element_has_class(driver, pnl, "expanded") if pnl else False
    visible_pnl  = is_panel_visible(driver, pnl) if pnl else False
    if expanded_btn and (expanded_pnl or visible_pnl):
        dbg("이미 확장 상태로 판단")
        return True

    # 클릭
    if not safe_click(driver, btn):
        return False
    dbg("클릭 → 확장 대기 시작")

    # 상태 대기
    end = time.time() + timeout
    while time.time() < end:
        try:
            ok_btn = element_has_class(driver, btn, "is-active") and (btn.get_attribute("aria-expanded") or "").lower() == "true"
        except Exception:
            ok_btn = False

        ok_pnl = False
        if pnl is not None:
            try:
                ok_pnl = element_has_class(driver, pnl, "expanded") \
                         and (pnl.get_attribute("aria-hidden") or "").lower() == "false" \
                         and is_panel_visible(driver, pnl)
            except Exception:
                ok_pnl = False
        else:
            ok_pnl = ok_btn

        if ok_btn and ok_pnl:
            dbg("확장 완료 신호 감지")
            return True
        time.sleep(0.15)

    warn("확장 대기 타임아웃")
    return False

def count_cards_in_scope(scope_el) -> int:
    c = 0
    try:
        nodes = scope_el.find_elements(By.CSS_SELECTOR,
            "ul.rate-content__list > li.rate-content__item, .rate-content-wrap, .rate-content__item"
        )
    except Exception:
        nodes = []
    for n in nodes:
        try:
            if n.is_displayed():
                c += 1
        except Exception:
            pass
    return c

# ---- 메인 플로우 ----
def main(url: str, headless: bool, slowmo: int, debug: bool):
    global DEBUG
    DEBUG = debug

    driver = setup_driver(headless=headless, slowmo=slowmo)
    wait = WebDriverWait(driver, 20)

    info(f"이동: {url}")
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
        step(f"메인탭 클릭: {main_name} (panel_id={mt.get('panel_id') or '-'})")
        disable_blocking_ui(driver)
        if not safe_click(driver, mt["el"]):
            warn(f"메인탭 클릭 실패: {main_name}")
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
            warn(f"패널 준비 실패: {main_name}")
            continue

        # 서브탭
        subs = get_subtabs_in_panel(main_panel)
        if subs:
            print(f"{main_name} [{', '.join([s['name'] for s in subs])}]")
            for st in subs:
                # 서브탭 메타 로그
                dbg(f"서브탭 meta: name='{st['name']}', code='{st.get('code') or ''}', panel_id='{st.get('panel_id') or ''}'")

                if not safe_click(driver, st["el"]):
                    print(f"{st['name']} 헤더 0개 -> [] (서브탭 클릭 실패)")
                    continue

                sel = wait_subtab_active(driver, st["el"], 6)
                dbg(f"aria-selected=true 대기 결과: {sel}")

                # --- 서브탭 고유 패널 스코프 ---
                sub_panel = main_panel
                pid = (st.get("panel_id") or "").strip()
                if pid:
                    try:
                        sub_panel = driver.find_element(By.ID, pid)
                    except Exception:
                        sub_panel = main_panel

                try:
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", sub_panel)
                except Exception:
                    pass
                scroll_pulse(driver, 2, 1000, 100)
                wait_panel_ready(driver, sub_panel, 9)

                # 수집
                meta = collect_accordion_meta(sub_panel, st.get("code") or None)
                if not meta:
                    # 코드필터로 비어오면 전체에서 시도
                    dbg("코드필터 결과 없음 → 전체 가시 버튼에서 재수집")
                    meta = collect_accordion_meta(sub_panel, None)

                print(f"{st['name']} 헤더 {len(meta)}개")
                for m in meta:
                    print(f"  - title:'{m['title']}', sub:'{m['sub']}', "
                          f"btn_id:'{m['btn_id']}', aria_controls:'{m['aria_controls']}', "
                          f"code:'{m['code']}', expanded:{m['expanded']}, class:'{m['btn_class']}'")

                # 확장/카드 카운트
                for m in meta:
                    title = m.get("title") or "(제목없음)"
                    btn, li, pnl = locate_btn_li_panel(driver, sub_panel, m)
                    if not btn:
                        print(f"    * [{title}] 헤더 버튼 탐색 실패")
                        continue
                    ok = open_accordion_and_wait(driver, btn, pnl, timeout=8)
                    if not ok:
                        print(f"    * [{title}] 확장 실패")
                        continue
                    scope_for_count = pnl if pnl is not None else li if li is not None else sub_panel
                    n_cards = count_cards_in_scope(scope_for_count)
                    print(f"    * [{title}] 확장 성공 → 카드 {n_cards}개")
                    time.sleep(0.2)
        else:
            # 서브탭 없음
            print(main_name)
            try:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", main_panel)
            except Exception:
                pass
            scroll_pulse(driver, 2, 1000, 100)
            wait_panel_ready(driver, main_panel, 9)

            meta = collect_accordion_meta(main_panel, None)
            print(f"{main_name} 헤더 {len(meta)}개")
            for m in meta:
                print(f"  - title:'{m['title']}', sub:'{m['sub']}', "
                      f"btn_id:'{m['btn_id']}', aria_controls:'{m['aria_controls']}', "
                      f"code:'{m['code']}', expanded:{m['expanded']}, class:'{m['btn_class']}'")

            for m in meta:
                title = m.get("title") or "(제목없음)"
                btn, li, pnl = locate_btn_li_panel(driver, main_panel, m)
                if not btn:
                    print(f"    * [{title}] 헤더 버튼 탐색 실패")
                    continue
                ok = open_accordion_and_wait(driver, btn, pnl, timeout=8)
                if not ok:
                    print(f"    * [{title}] 확장 실패")
                    continue
                scope_for_count = pnl if pnl is not None else li if li is not None else main_panel
                n_cards = count_cards_in_scope(scope_for_count)
                print(f"    * [{title}] 확장 성공 → 카드 {n_cards}개")
                time.sleep(0.2)

    driver.quit()

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=URL)
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--slowmo", type=int, default=0, help="implicit wait(ms). 추천: 0")
    ap.add_argument("--debug", action="store_true", help="자세한 디버그 로그 출력")
    args = ap.parse_args()
    main(args.url, args.headless, args.slowmo, args.debug)
